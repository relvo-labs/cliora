"""The read model behind Board, Backlog, List, Drawer, My Work and Overview (V2-P1).

Six screens, one answer to "how is this card doing". The point of the package is that
the answer is computed **once**, in :mod:`app.services.work.attention`, and every screen
renders the same object — the failure this replaces is six queries that agree today and
disagree after the next change to any one of them.
"""
