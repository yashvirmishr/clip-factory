"""GBNF grammar constraining the scorer to a valid judgement object.

Grammar sampling makes malformed JSON structurally impossible at decode time
(roughly 8-15% decode cost) instead of hoping for parseable output and paying
for retries. Note the deliberate use of ``{0,N}`` repetition - ``x? x? x?`` is
a documented llama.cpp performance trap.
"""

from __future__ import annotations

GRAMMAR = r'''
root ::= "{" ws "\"score\"" ws ":" ws score ws "," ws
         "\"hook\"" ws ":" ws short ws "," ws
         "\"title\"" ws ":" ws short ws "," ws
         "\"reason\"" ws ":" ws medium ws "," ws
         "\"understands_standalone\"" ws ":" ws bool ws "," ws
         "\"has_payoff\"" ws ":" ws bool ws "}"
score ::= [0-9] | [1-9] [0-9] | "100"
bool ::= "true" | "false"
short ::= "\"" schar{0,70} "\""
medium ::= "\"" schar{0,160} "\""
schar ::= [^"\\\x00-\x1f] | "\\" ["\\/bfnrt]
ws ::= [ \t\n]{0,4}
'''

CRITIQUE_GRAMMAR = r'''
root ::= "{" ws "\"standalone\"" ws ":" ws bool ws "," ws
         "\"payoff\"" ws ":" ws bool ws "," ws
         "\"verdict\"" ws ":" ws verdict ws "," ws
         "\"note\"" ws ":" ws medium ws "}"
verdict ::= "keep" | "drop"
bool ::= "true" | "false"
medium ::= "\"" schar{0,160} "\""
schar ::= [^"\\\x00-\x1f] | "\\" ["\\/bfnrt]
ws ::= [ \t\n]{0,4}
'''
