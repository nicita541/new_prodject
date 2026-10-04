# Launch reliability — 2026-10-05

The user explicitly removed local economy/money accounting. The active provider, server launch gate and browser control now ignore all historical balance/reservation/unknown-billing state. Historical `deepseek-spending.json` SHA-256 remains `AA414E5C105DEAD0546505848DFD3AFC9F981BF5B004EB547AB0E90CDCE8A5ED` after the change and test/browser checks; its bytes were not rewritten.

Validation: `tools/python/python.exe -m unittest discover -s tests -q` passed 343 tests in 17.179 seconds, with one existing Starlette/httpx deprecation warning. The earlier focused provider/job/API gate passed 55 tests. Obsolete monetary-accounting tests were replaced by current request/cancellation/cache/no-global-halt regressions; retired standalone balance-observation cases are no longer part of the active contract. OP/story/render regressions remain in the discovered suite.

Only the idle server listening on 127.0.0.1:8765 was restarted, after executable/PID/listener/idle checks. The actual in-app browser episode `926f51e4-4c81-47a9-b85c-d556493edf45` was refreshed, its previously selected `E01 - ТО Дубляжная - master.mp4` restored, and the enabled `Запустить монтаж` control observed. Browser text now describes two retries and omits the balance requirement. A completed new montage is a separate gate; this record does not assert new editorial/output acceptance.
