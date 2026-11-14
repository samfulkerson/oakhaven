"""Worked example: the Day 8 Reel ("The Horde"), exactly as it was published on 2026-11-14.

Copy this file to work/dayN.py for a new day and change it. Run from the repo root:
  python3 studio/examples/day8.py        (expects work/align.json from align_narration.py)
It writes work/day8.js and work/day8_segments.json.

Sentence numbers below are the ones align_narration.py printed for the Day 8 take (0 = "Ninety-seven of them hit the fence last night.").
"""
import os, sys
sys.path.insert(0, os.path.join(os.getcwd(), 'studio'))      # run from the repo root
from episode import Episode

ep = Episode('day8', 'work/align.json')
# --- where each block of narration sits. The hook (sentences 0-1) plays over the cold open; everything else is episode time.
ep.hook(0, 1, at=0.3)
ep.segment('A', 2, 3, at=1.0)       # "Oakhaven. Day eight." over the title card
ep.segment('B', 4, 5, at=5.4)       # 2 s of silent column footage first
ep.segment('C', 6, 7, at=10.6)
ep.segment('D', 8, 13, at=14.6)     # the names: each one gets a close-up
ep.segment('E', 14, 16, at=31.0)    # 3 s of silent fight before "By sunrise..."
ep.segment('F', 17, 27, at=39.0)    # daylight: police station
ep.segment('G', 28, 31, at=61.4)    # the diner
ep.segment('H', 32, 44, at=70.0)    # milestone + camp status
ep.segment('I', 45, 50, at=94.5)    # night again: the radio
ep.segment('J', 51, 56, at=108.0)   # the vote
ep.segment('K', 57, 58, at=117.0)   # end card
s, e = ep.s, ep.e
DUR = round(e(58) + 3.2, 1)
F = lambda n, w: ['follow', n, w]
cam = [[0, 450, 462, 520], [3.2, 452, 466, 320],
       [9.6, 448, 474, 250], [s(6), 462, 482, 220], [e(7), 440, 488, 200],
       [s(8), 430, 488, 200], [s(9) - .2, *F('Jaylozy', 120)], [s(10) - .25, *F('Jaylozy', 112)], [s(10) - .05, *F('Seth', 120)], [s(11) - .25, *F('Seth', 112)],
       [s(11) - .05, *F('Jeremy', 120)], [s(12) - .25, *F('Jeremy', 112)], [s(12) - .05, *F('Francis', 120)], [e(12) + .1, *F('Francis', 112)],
       [e(12) + .25, *F('Jack', 125)], [e(12) + 1.6, *F('Jack', 115)], [e(12) + 1.75, *F('Asa', 125)], [e(12) + 3.0, *F('Asa', 115)],
       [e(12) + 3.15, *F('Tanny', 125)], [e(13) + .2, *F('Tanny', 115)],
       [e(13) + .4, 426, 492, 175], [s(14), 426, 492, 210], [e(16) + .2, 426, 494, 400],
       [e(16) + .5, 424, 496, 300], [s(17) - .3, 424, 496, 280],
       [s(17) - .1, 330, 520, 360], [s(19) - .2, 300, 515, 220], [s(20), 290, 510, 170], [e(22), 286, 504, 150], [s(23), 276, 482, 120], [e(24), 276, 482, 104],
       [s(25), 276, 488, 160], [e(27), 276, 488, 190],
       [s(28) - .1, *F('Tanny', 160)], [s(30) - .3, *F('Tanny', 140)], [s(30), 554, 392, 130], [e(31) + .1, 554, 392, 112],
       [s(32) - .1, 584, 476, 170], [e(34), 584, 476, 130],
       [s(35), 470, 520, 230], [s(36) - .2, *F('Elder', 140)], [e(38) + .2, *F('Elder', 125)],
       [s(39), 424, 500, 140], [e(39), 424, 500, 128], [s(40), 424, 496, 230], [e(42), 424, 496, 260],
       [s(43), 470, 300, 900], [e(44) + .3, 470, 260, 1000],
       [e(44) + .6, 440, 466, 220], [s(45) + .2, 441, 462, 150], [s(48), 441, 460, 100], [e(50), 441, 460, 88],
       [s(51) - .3, 470, 560, 700], [e(56), 470, 560, 760], [DUR, 470, 600, 1100]]
hour = [[0, 19.0], [e(13), 19.2], [s(14), 19.4], [s(14) + .5, 29.0], [e(16) - .4, 30.6], [e(16) + .5, 31.2], [s(17), 32], [e(44), 38], [e(44) + 1.4, 49.5], [DUR, 50.2]]
D = [['Jaylozy', 457, 474], ['Seth', 457, 488], ['Jack', 452, 506, 1], ['Gary Finklestein', 457, 500], ['Jeremy', 404, 512], ['Francis', 416, 512],
     ['Asa', 430, 509, 1], ['Tanny', 442, 509, 1], ['Adam', 395, 512], ['Mateen', 393, 500], ['Victoria', 393, 486], ['Carl', 393, 472], ['Quinn', 393, 460]]
crowd = [d[0] for d in D] + ['Sam', 'Gabe']
events = [[0, 'defend', D],
          [0.5, 'horde', 26, [[488, 396], [488, 478]], 'e', 9],
          [2.5, 'horde', 18, [[566, 552], [470, 552], [470, 530]], 's', 9],
          [3.5, 'horde', 14, [[352, 552], [380, 552], [380, 528]], 's', 8],
          [4.5, 'horde', 12, [[352, 432], [376, 446], [376, 488]], 'w', 8],
          [13.5, 'horde', 16, [[488, 400], [488, 478]], 'e', 8],
          [18.0, 'horde', 14, [[560, 552], [470, 552], [470, 530]], 's', 7],
          [e(16) - 1.6, 'clearHorde'],
          [e(16) + .5, 'stand', [n for n in crowd if n not in ('Carl', 'Quinn', 'Asa', 'Tanny', 'Francis')]],
          [e(16) + .5, 'away', ['Carl', 'Quinn', 'Asa', 'Tanny', 'Francis', 'Javier', 'Elder']],
          [s(17) - .3, 'walk', 'Carl', [[372, 552], [276, 552], [276, 498]]], [s(17) - .1, 'walk', 'Quinn', [[384, 553], [280, 553], [280, 499]]],
          [s(17) + .1, 'walk', 'Javier', [[396, 551], [272, 551], [272, 499]]], [s(17) + .3, 'walk', 'Asa', [[408, 552], [284, 552], [284, 499]]],
          [s(25) + .6, 'away', ['Carl', 'Quinn', 'Javier', 'Asa']],
          [s(28) - 1.2, 'walk', 'Tanny', [[505, 432], [552, 432], [552, 384]]], [s(28) - 1.0, 'walk', 'Francis', [[497, 433], [557, 433], [557, 384]]],
          [e(31) + .3, 'away', ['Tanny', 'Francis']],
          [s(35) - 1.2, 'walk', 'Elder', [[488, 596], [488, 552], [424, 552], [424, 512]]],
          [e(42), 'stand', ['Elder']],
          [e(44) + .6, 'defend', [['Seth', 441, 457]]]]
captions = [[1.0, 3.3, 'title', 'OAKHAVEN', 'DAY 8'],
            [3.5, s(6) - .3, 'capTop', 'DAY 7 · 21:40 · THE HORDE'],
            [s(8), s(9) - .25, 'cap', '13 ON THE FENCE'],
            [s(9) - .2, s(10) - .25, 'cap', 'JAYLOZY · FIRE AXE'], [s(10) - .05, s(11) - .25, 'cap', 'SETH · MAUL'],
            [s(11) - .05, s(12) - .25, 'cap', 'JEREMY · BAYONET SPEAR'], [s(12) - .05, e(12) + .1, 'cap', 'FRANCIS · BOAT HOOK'],
            [e(12) + .25, e(12) + 1.6, 'cap', 'JACK · RIFLE'], [e(12) + 1.75, e(12) + 3.0, 'cap', 'ASA · SHOTGUN'], [e(12) + 3.15, e(13) + .2, 'cap', 'TANNY · REVOLVER'],
            [s(15), e(15) + .3, 'capTop', 'THE FENCE HELD'], [s(16), e(16) + .4, 'capTop', 'FENCE AT 60%'],
            [e(16) + .6, s(17) - .3, 'capTop', 'DAY 8 · 07:10'],
            [s(17), e(18) + .3, 'capTop', 'THE VOTE: POLICE, 4–1'],
            [s(19), e(19) + .2, 'cap', 'CARL, QUINN, JAVIER + ASA'],
            [s(20), e(22) + .2, 'cap', 'JAVIER: CONCUSSION · OUT UNTIL DAY 10'],
            [s(23), e(24) + .3, 'capTop', '+10 WATER'],
            [s(25), e(26) + .2, 'capTop', '2 MORE NIGHTS INSIDE'], [s(27), e(27) + .3, 'capTop', 'WHO CHAINED THE DOORS?'],
            [s(28), e(29) + .2, 'cap', 'TANNY + FRANCIS · THE DINER'], [s(30), e(31) + .3, 'capTop', '+6 WATER'],
            [s(32), e(33) + .2, 'capTop', '50 FOLLOWERS · THE PUMPS ARE RUNNING'], [s(34), e(35) + .2, 'capTop', '+2 FUEL EVERY NIGHT'],
            [s(36), e(38) + .2, 'cap', 'ELDER · MECHANIC'], [s(39), e(39) + .2, 'cap', 'SAM + GABE: BACK ON THEIR FEET'],
            [s(40), e(40) + .1, 'cap', '17 SURVIVORS'], [s(41), e(42) + .3, 'cap', 'FOOD: 2 DAYS · WATER: 1 DAY'],
            [s(43), e(44) + .3, 'capTop', 'NEXT HORDE: DAY 14'],
            [s(45), s(48) - .2, 'capTop', '88.1 · 02:14 AM'], [s(48), e(50) + .3, 'capTop', '"…FORT CORRAN…"'],
            [s(51) - .3, s(57) - .4, 'vote', 'WHILE THEY’RE INSIDE, WHERE DOES A SMALL GROUP GO?', ['GAS', 'GUN SHOP', 'MAPLE']],
            [s(57) - .3, DUR, 'card', 'WHO’S ON THE RADIO?', 'COMMENT YOUR NAME + JOB TO MOVE IN']]

ep.write(title='Day 8 · The Horde', dur=DUR, cam=cam, hour=hour, events=events, captions=captions,
         hook={'from': 28.3, 'tag': 'DAY 07 · 21:52', 'lines': ['97 OF THEM.', 'ONE FENCE.', '13 OF US.']})
