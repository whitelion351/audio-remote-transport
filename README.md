# audio-remote-transport
Transport audio to a remote system

An audio server/client system. Server grabs audio from chosen input device. Clients can connect to the server and be served the audio data, which they play over the chosen output device. Server can also take a file as input.

You can pass 'use_compression=' and a number <= 2 when creating the server to try out the data compression. Each compression mode gets progressively worse audio quality but does actually reduce bandwidth requirements. Compression 0 (no compression) however, works pretty well, Even across a wireless link. Audio quality defaults to a sample rate of 44100Khz with 16 bit samples, chunk size (frame size) of 2048 and buffer size of 102 chunks on server side and 96 on client side.

Implemented some "buffer magic" to keep clients near the start of the buffer to reduce latency.

## requirements
Python 3.x

pip install the following modules:

numpy

pyaudio

audioread

As stated in one of my other repos, Linux users need to apt-get install portaudiov19-dev. Windows users may need to `pip install pywin` though this was not needed for me when testing on windows 10 and python 3.5.4.

## options
pass `--configure_devices=True` on the command line or `configure_devices=True` when instancing the class to choose devices to use for input/output. Not needed when running the server for the first time. It will create a config file to read from during subsequent starts. This is only available for the server for now.

...To be continued
## todo
add options to choose different audio devices - DONE for server

audio data compression across the server/client connection - DONE for the time being. 2 compression modes available

Documentation for all the extra options I have added to the class. Most are buffer performance options
