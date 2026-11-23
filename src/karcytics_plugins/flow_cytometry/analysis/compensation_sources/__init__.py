"""Ways to obtain a spillover matrix.

Each method — read it from an FCS file, compute it from controls, import
it, or estimate it — is one ``MatrixSource``. The compensation view builds
its method selector and its Method setup page from ``MATRIX_SOURCES``, so
adding a method means adding a module here and listing it in ``registry``; the view doesn't
change.

A method is expected to be open about what it does: ``explanation`` says
how it works, ``inputs()`` shows what it will use before it runs, and
``SourceResult.report`` shows what the run rested on.

Whatever a method produces is a starting point: the view always follows it
with fine-tuning by hand.
"""
