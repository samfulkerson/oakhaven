"""Word timings for a narration take (pocketsphinx forced alignment), then the start/end of every sentence.

  python3 studio/align_narration.py NARRATION.mp3 SCRIPT.txt OUT.json

SCRIPT.txt is the exact text you pasted into ElevenLabs. OUT.json gets:
  {"words": [[word, start, end], ...], "sentences": [[index, start, end, text], ...]}
and the sentence table is printed, numbered from 0. Those numbers are what the episode file uses.

Names the recogniser doesn't know must be in PRON below (ARPAbet). If a word is missing, the script stops and says which:
add it, run again. Every new survivor name needs a line here.
"""
import json, os, re, subprocess, sys, tempfile, wave
from pocketsphinx import Decoder

PRON = {
    "oakhaven": "OW K HH EY V AH N", "mateen": "M AH T IY N", "francis": "F R AE N S IH S", "javier": "HH AA V Y EH R", "quinn": "K W IH N",
    "gabe": "G EY B", "gabe's": "G EY B Z", "tanny": "T AE N IY", "tanny's": "T AE N IY Z", "jaylozy": "JH EY L OW Z IY", "jaylozy's": "JH EY L OW Z IY Z",
    "corran": "K AO R AH N", "seth's": "S EH TH S", "asa": "AA S AH", "asa's": "AA S AH Z", "jeremy's": "JH EH R AH M IY Z", "jack's": "JH AE K S",
    "squad's": "S K W AA D Z", "finklestein": "F IH NG K AH L S T IY N", "reyes": "R EY EH S", "millbrook": "M IH L B R UH K", "gunsmith": "G AH N S M IH TH",
    "sam's": "S AE M Z", "carl's": "K AA R L Z", "quinn's": "K W IH N Z", "elder's": "EH L D ER Z", "victoria's": "V IH K T AO R IY AH Z",
}


def words_of(text):
    w = re.sub(r"[^a-z' \-]", " ", text.lower()).replace('-', ' ').split()
    return [x.strip("'") if not x.endswith("'s") else x for x in w]


def sentences_of(text):
    return [s.strip() for s in re.findall(r'[^.?!]+[.?!]+', text)]


def main():
    mp3, script, out = sys.argv[1:4]
    text = open(script).read().strip()
    wav = tempfile.mktemp(suffix='.wav')
    subprocess.run(['ffmpeg', '-y', '-loglevel', 'error', '-i', mp3, '-ar', '16000', '-ac', '1', wav], check=True)
    d = Decoder(samprate=16000, bestpath=False)
    for w, p in PRON.items():
        try: d.add_word(w, p, True)
        except RuntimeError: pass
    ws = words_of(text)
    missing = sorted({w for w in ws if d.lookup_word(w) is None})
    if missing:
        sys.exit(f"Add pronunciations for these words to PRON in {__file__}: {missing}")
    d.set_align_text(' '.join(ws))
    data = wave.open(wav).readframes(wave.open(wav).getnframes())
    d.start_utt(); d.process_raw(data, full_utt=True); d.end_utt()
    d.set_alignment(); d.start_utt(); d.process_raw(data, full_utt=True); d.end_utt()
    al = [(s.name, s.start / 100, (s.start + s.duration) / 100) for s in d.get_alignment()]
    al = [a for a in al if a[0] not in ('<sil>', '<s>', '</s>')]
    if len(al) != len(ws):
        sys.exit(f'aligned {len(al)} words but the script has {len(ws)}: is SCRIPT.txt exactly what was generated?')
    sents, i = [], 0
    for k, s in enumerate(sentences_of(text)):
        n = len(words_of(s))
        sents.append([k, round(al[i][1], 2), round(al[i + n - 1][2], 2), s]); i += n
    json.dump({'words': al, 'sentences': sents}, open(out, 'w'), indent=0)
    for k, a, b, s in sents:
        print(f'{k:3d}  {a:7.2f} - {b:7.2f}  {s}')
    os.remove(wav)


if __name__ == '__main__':
    main()
