"""Make a JavaScript snippet that applies your local edits of ONE text file to GitHub's web editor, safely.

  git fetch && python3 studio/github_patch.py PATH/IN/REPO OUT.js

The snippet checks the editor holds exactly origin/main's version (sha256) before changing anything, applies only the
changed lines, and checks the result is byte-for-byte your local file. It prints OK, OLD MISMATCH (someone changed the file
on GitHub: fetch, redo your edit on top, regenerate) or NEW MISMATCH (don't commit; regenerate).
Run it with the browser's javascript tool on https://github.com/samfulkerson/oakhaven/edit/main/PATH/IN/REPO, then commit
(see README, "Pushing to GitHub").
"""
import difflib, hashlib, json, subprocess, sys

path, out = sys.argv[1], sys.argv[2]
old = subprocess.run(['git', 'show', 'origin/main:' + path], capture_output=True, text=True, check=True).stdout
new = open(path, encoding='utf-8').read()
u16 = lambda s: len(s.encode('utf-16-le')) // 2          # CodeMirror counts UTF-16 code units
ol, nl = old.splitlines(True), new.splitlines(True)
off = [0]
for l in ol: off.append(off[-1] + u16(l))
ch = [[off[i1], off[i2], ''.join(nl[j1:j2])] for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ol, nl, autojunk=False).get_opcodes() if tag != 'equal']
sh = lambda t: hashlib.sha256(t.encode()).hexdigest()
js = f"""for(let i=0;i<30&&!document.querySelector('.cm-content');i++) await new Promise(r=>setTimeout(r,500));
const view=document.querySelector('.cm-content').cmTile.view;
const sha=async t=>[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(t)))].map(b=>b.toString(16).padStart(2,'0')).join('');
const before=await sha(view.state.doc.toString());
if(before!=='{sh(old)}') 'OLD MISMATCH '+before; else {{
view.dispatch({{changes:{json.dumps(ch, ensure_ascii=False)}.map(([from,to,insert])=>({{from,to,insert}}))}});
const after=await sha(view.state.doc.toString()); after==='{sh(new)}'?'OK':'NEW MISMATCH '+after }}"""
open(out, 'w').write(js)
print(f'{path}: {len(ch)} change(s), snippet {len(js)} chars -> {out}')
