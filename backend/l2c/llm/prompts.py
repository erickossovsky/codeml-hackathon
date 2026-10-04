"""Prompt templates. Every prompt asks one question about one or two elements. The elements are shown
as the compact free-form JSON read from the page (see `compact.py`), followed by two worked examples.

Templates are versioned: changing any wording means a new version string.
"""

from __future__ import annotations

OPTIONS = ["yes", "no"]

LINK_VERSION = "link-v4"
LINK_SYSTEM = (
    "You judge a structural drawing. You get one text note and one drawn object, each as JSON read from the page. "
    "Answer yes if the note most likely labels or describes that object, otherwise no.\n"
    'Example 1\nNOTE: {"text":"COL. 400x500 | ARM.: 6-20M","grid":"B-3"}\n'
    'OBJECT: {"shape":"solid","size_pt":[15,19],"grid":"B-3","gap_pt":35,"leader_line_to_note":true}\nANSWER: yes\n'
    'Example 2\nNOTE: {"text":"COL. 400x500 | ARM.: 6-20M","grid":"B-3"}\n'
    'OBJECT: {"shape":"linework","size_pt":[800,3],"grid":"F-9","gap_pt":650}\nANSWER: no\n'
    "Answer with one word: yes or no."
)

GROUP_VERSION = "group-v2"
GROUP_SYSTEM = (
    "You decide which of two candidates a text note on a structural drawing belongs to. "
    "The note is JSON read from the page. Answer yes if it belongs to candidate A, no if it belongs to candidate B.\n"
    'Example 1\nNOTE: {"text":"VERT: 6 20M M1-01 | ETRI: 8 10M @300"}\nCANDIDATE A: B-3\nCANDIDATE B: B-4\n'
    "Does the note belong to candidate A? ANSWER: yes\n"
    "Answer with one word: yes or no."
)

MATCH_VERSION = "match-v4"
MATCH_SYSTEM = (
    "You decide whether a PLAN element and a SHOP element describe the same physical object. "
    "Each is JSON read from a drawing. Answer yes if they are the same object, otherwise no.\n"
    'Example 1\nPLAN: {"kind":"column","grid":"B-3","level":"N3","bars":["ARM.: 6-20M"],"chars":{"section":[400,500]}}\n'
    'SHOP: {"kind":"column","name":"B-3","grid":"B-3","level":"N3..N4","bars":["6 20M 20Z3150."],"chars":{"section":[400,500]}}\nANSWER: yes\n'
    'Example 2\nPLAN: {"kind":"column","grid":"B-3","level":"N3","chars":{"section":[400,500]}}\n'
    'SHOP: {"kind":"column","name":"F-9","grid":"F-9","level":"N3..N4","chars":{"section":[350,450]}}\nANSWER: no\n'
    "Answer with one word: yes or no."
)

PROPERTY_VERSION = "property-v2"
PROPERTY_SYSTEM = (
    "You compare one property written on a plan with one property written on a shop drawing for the "
    "same object. Values are already converted to one unit. Answer 'same' if they say the same thing "
    "about the same property and agree, 'different' if they are the same property but the values differ, "
    "and 'unrelated' if they are not the same property.\n"
    "Example 1\nPLAN: vertical bars 6 x 20M\nSHOP: vertical bars 6 x 20M, mark 20Z3150\nANSWER: same\n"
    "Example 2\nPLAN: vertical bars 6 x 20M\nSHOP: vertical bars 6 x 25M\nANSWER: different\n"
    "Example 3\nPLAN: vertical bars 6 x 20M\nSHOP: tie spacing 200 mm\nANSWER: unrelated\n"
    "Answer with one word: same, different or unrelated."
)
PROPERTY_OPTIONS = ["same", "different", "unrelated"]

EXPLAIN_VERSION = "explain-v1"
EXPLAIN_SYSTEM = (
    "You write one short sentence for an engineer about one difference found between a structural plan "
    "and a shop drawing. State the property, the plan value and the shop value. No advice."
)
