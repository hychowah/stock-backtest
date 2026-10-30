# Offline copy ownership peers

These two files are exact Git copies from revision
`d877cb40faf0c643e4c4e386e87b6074e8cca5d2`:

| File | SHA-256 |
|---|---|
| scripts/cache_access.py | `5dc7463285d6ae1d0dba58fdf901f832ccc59714e4ff676d108e05d9247f9713` |
| website/runtime_access.py | `c1e65debe45102ac5f32b63da104cda141918a9bd0c5a136ea2b8e766e8b12eb` |

The offline copier accepts only this installed ownership binding. Its tests
execute these private copies on synthetic files in peer processes. They verify
that the old shared source owner and writable financial owner interoperate with
the current exclusive source owner and read-only financial observer. The tests
do not execute installed modules or open installed inputs.

Keep these files unchanged. A different revision needs a separate compatibility
decision and native peer checks. Offline exclusion does not establish live
priority. A new startup can wait or time out while capture owns the source.
