from core.kimage import KImage
from kivy.properties import StringProperty
from kivy.clock import Clock
import cv2
import numpy as np
import threading
import socket
import os
from Detection.EmotionDetector import EmotionDetector
from Detection.EmotionStreamHandler import EmotionStreamHandler
from Detection.Model.FrameInfo import FrameInfo
from Detection.Model.SessionInfo import SessionInfo
from Detection.SessionEvaluator import SessionEvaluator
from PathUtil import resource_path
from helpers.ksocket import KSocketClient
from .warning_dialog import WarningDialog

class CameraImage(KImage):

  def __init__(self, **kwargs):
    super(CameraImage, self).__init__(**kwargs)
    self.stream_port = 9090
    self.term_port = 9091
    self.status = 'ended'
    self.emotion_color = StringProperty(None)
    self.detect_thread = None
    self.warning_dialog = WarningDialog(
      auto_dismiss=False,
      title="BE CAREFUL",
      text="Your expression seems like critically negative!"
    )
    self.is_warning = False

  def open_camera(self):
    self.status = 'started'
    self.detect_thread = threading.Thread(target=self.detect_from_camera, daemon=True)
    self.detect_thread.start()
    Clock.schedule_interval(self.client_recv, 0.05)

  def close_camera(self):
    self.status = 'ended'

  def client_recv(self, *args):
    if self.detect_thread.is_alive():
      try:
        self.client_stream_socket = KSocketClient()
        self.client_stream_socket.kconnect(socket.gethostname(), self.stream_port)
        str_encoded = self.client_stream_socket.kreceive()
        nparr = np.fromstring(str_encoded, np.uint8)
        if nparr.size != 0:
          img_decoded = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
          if self.status == 'started':
            cv2.imwrite(resource_path('assets/v.jpg'), img_decoded)
            self.source = 'assets/v.jpg'
            self.reload()
            if self.emotion_color is not None:
              self.app.set_emotion_color(self.emotion_color)
          else:
            self.source = 'assets/video.jpg'
            self.reload()
            os.remove('assets/v.jpg')
      except ConnectionRefusedError:
        print('Hello ConnectionRefusedError')
    else:
      if self.status == 'started':
        self.detect_thread = threading.Thread(target=self.detect_from_camera, daemon=True)
        self.detect_thread.start()

  def show_warning_dialog(self):
    self.warning_dialog.open()

  def hide_warning_dialog(self):
    self.warning_dialog.dismiss()

  def detect_from_camera(self):
    try:
      server_stream_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
      server_stream_socket.bind((socket.gethostname(), self.stream_port))
      server_stream_socket.listen()
      # prevents openCL usage and unnecessary logging messages
      cv2.ocl.setUseOpenCL(False)

      # dictionary which assigns each label an emotion (alphabetical order)
      emotion_dict = {7: "No face detected", 0: "Angry", 1: "Disgusted", 2: "Fearful", 3: "Happy", 4: "Neutral", 5: "Sad", 6: "Surprised"}
      emotion_colors = {7: "#000000", 0: "#FF005A", 1: "#33CC33", 2: "#9933FF", 3: "#FFCC00", 4: "#996600", 5: "#0099FF", 6: "#33CCCC"}

      cap = cv2.VideoCapture(0)
      streamHandler = EmotionStreamHandler()
      emotionDetector = EmotionDetector()
      sessionInfo = SessionInfo(None, None, None, None)

      while True:
        (connection, address) = server_stream_socket.accept()
        hasFace = False
        # Find haar cascade to draw bounding box around face
        ret, frame = cap.read()
        if not ret:
          break
        frame = cv2.flip(frame, 1)

        facecasc = cv2.CascadeClassifier(resource_path('Detection\haarcascade_frontalface_default.xml'))
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        faces = facecasc.detectMultiScale(gray,scaleFactor=1.3, minNeighbors=5)
        frameInfo = FrameInfo(None, None, None)

        for (x, y, w, h) in faces:
          hasFace = True
          roi_gray = gray[y:y + h, x:x + w]
          cropped_img = np.expand_dims(np.expand_dims(cv2.resize(roi_gray, (48, 48)), -1), 0)
          maxindex = emotionDetector.detectEmotion(cropped_img)
          cv2.rectangle(frame, (x, y-50), (x+w, y+h+10), (255, 0, 0), 2)
          cv2.putText(frame, emotion_dict[maxindex], (x+20, y-60), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2, cv2.LINE_AA)

          streamHandler.addFrame(maxindex)
          self.emotion_color = emotion_colors[maxindex]
        if hasFace is not True:
          streamHandler.addFrame(7)
          self.emotion_color = emotion_colors[7]

        if streamHandler.warning:
          if not self.warning_dialog._window:
            self.show_warning_dialog()
        else:
          if self.warning_dialog._window:
            self.hide_warning_dialog()

        img = cv2.resize(frame,(400,300),interpolation = cv2.INTER_CUBIC)
        encode_param = [int(cv2.IMWRITE_JPEG_QUALITY), 90]
        result, img_encoded = cv2.imencode('.jpg', img, encode_param)
        data_encoded = np.array(img_encoded)
        str_encoded = data_encoded.tostring()
        connection.sendall(str_encoded)
        connection.close()
        if self.status == 'ended':
          break
      Clock.unschedule(self.client_recv)
      sessionInfo = streamHandler.finish()
      for i in range(0, len(sessionInfo.periods)):
        print("===={}==== size: {}".format(emotion_dict[i], len(sessionInfo.periods[i])))
        for period in sessionInfo.periods[i]:
          print(period.__dict__)
          duration = int(round((period.periodEnd - period.periodStart)*1000))
      sessionEvaluator = SessionEvaluator()
      sessionEvaluator.evaluate(sessionInfo)
      cap.release()
      cv2.destroyAllWindows()
    except:
      pass
