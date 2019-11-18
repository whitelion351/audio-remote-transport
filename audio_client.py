from time import sleep
from threading import Thread
import numpy as np
import socket
import pyaudio


class AudioClient:
    # noinspection SpellCheckingInspection
    def __init__(self, chunk=2048, audio_format=pyaudio.paInt16, channels=1, rate=44100, audio_buffer_size=96):
        # constants
        self.CHUNK = chunk             # samples per frame
        self.FORMAT = audio_format     # audio format (bytes per sample?)
        self.CHANNELS = channels       # 1 for mono, 2 for stereo
        self.RATE = rate               # samples per second
        self.live_stream = None        # pyaudio object
        self.connection = None         # connection to server
        self.server_address = None
        self.server_port = None
        self.is_connected = False
        self.buffer_size = audio_buffer_size
        self.audio_buffer = []
        self.use_compression = 0
        self.last_sample = 0           # used for compression mode 1
        self.threads = {}

    def create_audio_stream(self):
        """ Create pyaudio object and open stream for reading/writing audio data"""
        stream = pyaudio.PyAudio()
        print("starting new audio stream")
        self.live_stream = stream.open(
            format=self.FORMAT,
            channels=self.CHANNELS,
            rate=self.RATE,
            input=False,
            output=True,
            frames_per_buffer=self.CHUNK
        )

        print('audio stream running')

    def set_server(self, address=None, port=None):
        """Sets server IP and port. Set this before calling play_audio_stream"""
        if address is None or port is None:
            print("you need to specify an address and port, ya big ninnie")
        else:
            self.server_address = address
            self.server_port = port

    def connect_to_server(self, retry=None):
        """Connects to server and gets audio parameters for creating the pyaudio object, i.e. sample rate, etc
        Normally called by play_audio_stream"""
        retries = retry if retry is not None else 3
        print("connecting to audio server at {}:{}".format(self.server_address, self.server_port))
        while retries > 0 and not self.is_connected:
            try:
                self.connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.connection.connect((self.server_address, self.server_port))
                self.connection.settimeout(3)
                info = "AudioClient,"+str(self.buffer_size)
                self.connection.send(bytes(info, "utf-8"))
                data = self.connection.recv(self.CHUNK)
                data = data.decode("utf-8").split(sep=",")
                data = [int(d) for d in data if d != ","]
                self.RATE = data[0]
                self.CHUNK = data[1]
                self.use_compression = data[2]
                print("using samplerate: {}, chunksize: {}, compression: {}".format(self.RATE, self.CHUNK,
                                                                                    self.use_compression))
                self.connection.send(bytes("ok", "utf-8"))
            except Exception as e:
                print(e)
                retries -= 1
                print("connection failed. retries remaining:", retries)
                sleep(2)
            else:
                self.is_connected = True
                print("connection established")
                self.create_audio_stream()

    def play_audio_stream(self):
        """Called after setting server IP and port.
        Takes care of creating buffer thread and writing audio data"""
        done = False
        while done is False:
            if "buffer_control" not in self.threads.keys():
                print("starting buffer thread")
                thread = Thread(target=self.buffer_control, name="buffer_control", daemon=True)
                self.threads[thread.name] = thread
                self.connect_to_server()
                self.fill_buffer()
                thread.start()
            while self.live_stream.get_write_available() > self.CHUNK:
                if len(self.audio_buffer) == 0:
                    print("buffer empty")
                    sleep(1)
                    break
                data = self.audio_buffer.pop(0) if len(self.audio_buffer) > 0 else None
                self.write_audio_to_stream(data)

    def buffer_control(self):
        """Buffer thread function. Maintains connection to server and keeps buffer full"""
        while True:
            if not self.is_connected:
                self.connect_to_server()
            if len(self.audio_buffer) < self.buffer_size:
                self.fill_buffer()

    def fill_buffer(self):
        """Grabs audio data from server, applies compression if enabled, and adds to buffer"""
        while len(self.audio_buffer) < self.buffer_size and self.is_connected:
            data = self.get_next_chunk()
            data = self.decompress_data(data) if self.use_compression > 0 else data
            if data is None:
                print("a chunk was None")
                break
            else:
                self.audio_buffer.append(data)

    def get_next_chunk(self):
        """gets next chunk of audio data from server. When using compression, a 2 byte header is received first
        which contains the amount of data to expect. Otherwise the amount of data is always self.CHUNK * 2"""
        data_size = self.CHUNK if self.use_compression > 0 else self.CHUNK * 2
        data = bytes()
        while len(data) < data_size:
            try:
                chunk_data = self.connection.recv(data_size)
                if len(chunk_data) == 0:
                    raise ConnectionError("chunk data was length 0")
                elif len(data) == 0 and len(chunk_data) == 2:
                    if chunk_data == bytes(2):
                        data = bytes(data_size)
                    else:
                        data_size = np.frombuffer(chunk_data, dtype=np.int16)[0]
                        self.connection.send(chunk_data)
                else:
                    data += chunk_data
            except (ConnectionError, socket.timeout) as e:
                print("failed getting chunk:", e)
                self.connection.close()
                self.is_connected = False
                return None
        self.connection.send(bytes("ok", "utf-8"))
        return data

    def decompress_data(self, data):
        """Called when using compression. passes compressed data to the proper decompress function
        I could probably use a higher order function to achieve the same result."""
        if data is None:
            return data
        elif data == bytes(2):
            return bytes(self.CHUNK * 2)
        elif self.use_compression == 1:
            return self.decompress_interpolate(data)
        elif self.use_compression == 2:
            return self.decompress_data_fill(data)

    def decompress_interpolate(self, data):
        """self explanatory. Interpolates between all values sent from server.
        self.last_sample is always the first element and is set by the last element of previous data"""
        x = [i for i in range(self.CHUNK)]
        xp = np.array(range(-1, len(data), 2))
        fp = np.zeros((len(xp),))
        fp[0] = self.last_sample
        fp[1:] = np.frombuffer(data, dtype=np.int16)
        new_data = np.interp(x, xp, fp).astype(np.int16)
        self.last_sample = new_data[-1]
        new_data = new_data.tobytes()
        return new_data

    def decompress_data_fill(self, data):
        """magnum opus. Kind of hard to explain how this works in a doc string. just call it magic"""
        data = np.frombuffer(data, dtype=np.int16)
        x = [i for i in range(self.CHUNK)]
        xp = data[1:data[0]+1]
        fp = data[data[0]+1:]
        try:
            new_data = np.interp(x, xp, fp).astype(np.int16)
        except ValueError as e:
            print(e)
            print("length x {} xp {} fp {}".format(len(x), len(xp), len(fp)))
            return bytes(self.CHUNK * 2)
        new_data = new_data.tobytes()
        return new_data

    def write_audio_to_stream(self, data):
        if data is None:
            return
        self.live_stream.write(data)
        return


if __name__ == "__main__":
    audio = AudioClient()
    audio.set_server("192.168.5.121", 1060)
    audio.play_audio_stream()
