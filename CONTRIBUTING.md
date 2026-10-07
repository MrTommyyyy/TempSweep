# Contributing

Describe the task you were doing, TempSweep version, Windows version and what you expected. Include a small disposable example when possible. Remove private paths and filenames before sharing reports. Do not upload personal files or crash-dump contents.

Run the suite from the source folder:

```sh
python -m unittest discover -s tests -v
python demo.py
```

Windows runs actual Tk widgets and native file-handle tests. Desktop and Windows-specific tests are skipped on other platforms; an available desktop can opt in to Tk checks with `TEMPSWEEP_GUI_TESTS=1`. The Bin APIs are mocked for write tests. Never add a test that empties a real Recycle Bin or cleans a developer’s temp folder.

Use temporary fixture folders for deletion changes. Include a regression test for paths outside the cleanup root, recent files and any affected confirmation or failure behavior. Keep file deletion tied to a fresh in-memory preview; do not add deletion-plan imports from untrusted reports.

New cleanup categories need a clear fixed scope and documented tradeoffs. Do not expand the default to personal documents, browser profiles, registry entries or arbitrary directories. Do not request elevation or change file permissions automatically.

Version changes must update the application, Windows workflow, packaged smoke checks and release documents together. Existing release downloads are preserved; publish fixes as a new version.
