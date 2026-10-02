"""The naming language, outcome vocabulary, and no-links rule a sealed bundle obeys.

These are the rules that everything else in the package inherits, so they are tested
first and tested as *rules* rather than as incidental behaviour: each one is stated here
with the reason it exists, and a test that stops firing is a defect the gate should catch.

Three groups:

* **The run id.** Lower-case, single segment, project identifier convention, and never a
  Windows device name. Two spellings that collide on a case-insensitive filesystem are not
  one vocabulary.
* **The bundle path.** Relative, already normalized, ``/``-separated, no whitespace, no
  traversal, no drive, and never a name the seal writes. The traversal and device-name
  halves are *not* re-tested as this package's own logic — they are the RES-230 gate being
  reused, and the test that matters is that a rejection still happens through this module.
* **Links and reparse points.** A symlink, a junction, and any other reparse point are
  refused, and a hard link is deliberately not. The junction case is the one that matters
  on the primary platform, because ``is_symlink()`` reports a junction as an ordinary
  directory.
"""
