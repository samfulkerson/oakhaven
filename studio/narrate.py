"""Record narration with the ElevenLabs API (the "Record narration" workflow runs this; the key lives in the repo secret ELEVENLABS_API_KEY).

A request is a small JSON file in studio/narration/, written after Sam approves the script:
    {"lines": [{"voice": "atlas", "text": "Oakhaven. Day fifteen."},
               {"voice": "wayne", "text": "[quietly] Much obliged, friend."}]}
One voice -> plain text to speech. Several voices -> one text-to-dialogue take, so the voices share a single recording.
Writes studio/narration/<name>.mp3 next to the request. Usage: python studio/narrate.py studio/narration/day15.json
"""
import json, os, sys, urllib.request, urllib.error

VOICES = {                                   # the cast: short names -> ElevenLabs voice IDs (all in Sam's My Voices)
    "atlas": "3YzGaTGef0x5PLEK9yGq",          # Atlas - Deep, Gravelly Narrator: every daily Reel
    "wayne": "a4BsmeT8RITKlxlCY9PO",          # Brother Wayne - Warm Southern Preacher: Elias
    "lasean": "bQxW1c7YCr6VQgQhw8KX",         # LaSean Pickens: Officer Reyes
}
MODEL = "eleven_v4"
SETTINGS = {"stability": 0.5, "similarity": 0.75}    # what the web app was set to (s50, sim75)
API = "https://api.elevenlabs.io/v1"


def call(url, body, key):
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"xi-api-key": key, "Content-Type": "application/json", "Accept": "audio/mpeg"})
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        sys.exit(f"ElevenLabs said {e.code}: {e.read().decode(errors='replace')[:600]}")


def main(path):
    key = os.environ.get("ELEVENLABS_API_KEY")
    if not key:
        sys.exit("No ELEVENLABS_API_KEY: add it under Settings > Secrets and variables > Actions.")
    req = json.load(open(path, encoding="utf-8"))
    lines = req["lines"]
    for ln in lines:
        if ln["voice"] not in VOICES:
            sys.exit(f"Unknown voice '{ln['voice']}'. Known: {', '.join(VOICES)}")
    chars = sum(len(ln["text"]) for ln in lines)
    voices = {ln["voice"] for ln in lines}
    model = req.get("model", MODEL)
    if len(voices) == 1:
        text = " ".join(ln["text"] for ln in lines)
        audio = call(f"{API}/text-to-speech/{VOICES[lines[0]['voice']]}?output_format=mp3_44100_128", {
            "text": text, "model_id": model,
            "voice_settings": {"stability": SETTINGS["stability"], "similarity_boost": SETTINGS["similarity"]}}, key)
    else:
        audio = call(f"{API}/text-to-dialogue?output_format=mp3_44100_128", {
            "inputs": [{"text": ln["text"], "voice_id": VOICES[ln["voice"]]} for ln in lines],
            "model_id": model, "settings": SETTINGS}, key)
    out = os.path.splitext(path)[0] + ".mp3"
    open(out, "wb").write(audio)
    print(f"{out}: {len(audio) // 1024} KB, {chars} characters, voices: {', '.join(sorted(voices))}, model {model}")


if __name__ == "__main__":
    main(sys.argv[1])
