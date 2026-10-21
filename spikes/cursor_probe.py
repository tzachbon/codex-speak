"""S1 spike: can the Cursor desktop sign-in list models, chat, and transcribe? Prints shapes and lengths only."""
import struct
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request

from harness_discussion import cursor_auth
from harness_discussion.cursor_tts import _ld, _varint, decode

BASE = "https://api2.cursor.sh/aiserver.v1.AiService/"


def unary(method, body):
    req = urllib.request.Request(BASE + method, data=body, headers={
        "Content-Type": "application/proto", "Connect-Protocol-Version": "1",
        "Authorization": f"Bearer {cursor_auth.token()}"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        print(method, "HTTP", e.code, e.read()[:300])
        raise


def repeated(data, field):
    """Every length-delimited value of one field."""
    out, i = [], 0
    from harness_discussion.cursor_tts import _read_varint
    while i < len(data):
        key, i = _read_varint(data, i)
        wire = key & 7
        if wire == 0:
            _, i = _read_varint(data, i)
            continue
        size = {1: 8, 5: 4}.get(wire)
        if wire == 2:
            size, i = _read_varint(data, i)
        if key >> 3 == field:
            out.append(data[i:i + size])
        i += size
    return out


def models():
    data = unary("AvailableModels", _varint(5 << 3) + b"\x01")  # use_model_parameters = true
    for m in repeated(data, 2):
        f = decode(m)
        print(" ", f.get(1, b"").decode(), "thinking" if f.get(9) else "", (f.get(17) or b"").decode())
    print("models:", len(repeated(data, 2)))


def transcribe():
    with tempfile.TemporaryDirectory() as d:
        path = f"{d}/a.wav"
        subprocess.run(["say", "-o", path, "--file-format=WAVE", "--data-format=LEI16@16000",
                        "Please check the deployment logs tomorrow morning."], check=True)
        audio = open(path, "rb").read()
    data = unary("TranscribeAudio", _ld(1, audio) + _ld(2, b"audio/wav"))
    print("transcript:", decode(data).get(1, b"").decode())


def stream(method, body, base=BASE):
    """Connect server-streaming call: enveloped request, then frames of (flags, length, message)."""
    req = urllib.request.Request(base + method, data=b"\0" + struct.pack(">I", len(body)) + body, headers={
        "Content-Type": "application/connect+proto", "Connect-Protocol-Version": "1",
        "Authorization": f"Bearer {cursor_auth.token()}"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        while header := resp.read(5):
            flags, size = header[0], struct.unpack(">I", header[1:])[0]
            data = resp.read(size)
            yield flags, data


def chat(model=None):
    import uuid
    model = model or (sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "chat" else "gpt-5.4-mini")
    prompt = ("Rewrite the text between the markers as a short friendly chat message. Return only the rewritten text.\n"
              "<<<\nhey i think we should of shipped the fix yesterday lol can u check the logs\n>>>")
    message = _ld(1, prompt.encode()) + _varint(2 << 3) + _varint(1) + _ld(13, str(uuid.uuid4()).encode())
    details = _ld(1, model.encode()) + _varint(3 << 3) + b"\x01"  # ghost mode: privacy mode on
    level = sys.argv[3] if len(sys.argv) > 3 else ""
    flag = lambda n: _varint(n << 3) + b"\x01"
    body = (_ld(1, message) + _ld(5, details) + flag(22) + _ld(23, str(uuid.uuid4()).encode())
            + _varint(46 << 3) + _varint(1) + flag(48) + flag(50))  # is_chat, CHAT mode, no tools, chat prompt
    if level:
        body += _varint(49 << 3) + _varint({"medium": 1, "high": 2}[level])
    text = []
    for flags, data in stream("StreamUnifiedChat", body, "https://api2.cursor.sh/aiserver.v1.ChatService/"):
        if flags & 2:
            print("trailer:", data[:200])
        else:
            text.append(decode(data).get(1, b"").decode())
    print(model, "reply:", "".join(text))


if __name__ == "__main__":
    if sys.argv[1:2] == ["chat"]:
        chat()
        sys.exit()
    for step in sys.argv[1:] or ["models", "transcribe"]:
        globals()[step]()
