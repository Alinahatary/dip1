import eel
import os
import docopt
import subprocess
eel.init('web')
ip = "192.168.154.128"
mode = "train"
@eel.expose
def loggy(log, passw):
     print(log, passw)
     subprocess.run(["python", "DeepExploit.py"])

# @eel.expose
# def pyt_in_js(x):
#      print(x)

eel.start('test.html', size=(400, 200))
