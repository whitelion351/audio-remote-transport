# audio-remote-transport
Transport audio to a remote system

An audio server/client system. Server grabs audio from chosen input device. Clients can connect to the server and be served the audio data, which they play over the chosen output device. Server can also take a file as input.

You can pass 'use_compression=' and a number <= 2 when creating the server to try out the data compression. Compression 1 works but its not great. Compression 2 does not work but is a work in progress. Compression 0 (no compression) however, works pretty well, Even across a wireless link. Audio quality defaults to a sample rate of 44100Khz with 16 bit samples, chunk size of 2048 and buffer size of 96 chunks on both server and client side.

Implemented some "buffer magic" to keep clients near the start of the buffer to reduce latency.

## requirements
Python 3.5 or above (only tested on Linux x64)

pip install the following modules:

pyaudio

audioread

As stated in one of my other repos, Linux users need to apt-get install portaudiov19-dev. Windows users need pip install pywin though that is untested. I only use windows to play League of Legends.

## options
pass '--configure_devices=True' on the command line or 'configure_devices=True' when instancing the class to choose devices to use for input/output. Not needed when running the server for the first time. It will create a config file to read from during subsequent starts. This is only available for the server for now.

...To be continued
## todo
add options to choose different audio devices - DONE for server

audio data compression across the server/client connection - work in progress

Documentation for all the extra options I have added to the class. Most are buffer performance options
