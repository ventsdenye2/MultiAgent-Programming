# Layered application configuration

Only modify `merge.py` and `settings.py`. Python 3.12, standard library only.

Implement `merge.merge_layers(*layers)` for dictionary layers: later values win;
when both values are dictionaries, recursively merge. Lists and all other values
(including None) replace the earlier value. A non-dictionary layer raises
TypeError. The returned tree must share no mutable dictionaries/lists with inputs;
inputs must remain unchanged.

Implement `settings.build_config(defaults, overrides, environ)`: first merge the
two dictionary layers, then apply recognized environment keys. `APP_TIMEOUT`
sets `result['network']['timeout']` to a positive base-10 ASCII integer; surrounding
whitespace and an optional leading + are accepted, zero/negative/decimal text
are rejected with ValueError. `APP_DEBUG` sets `result['debug']` to a bool, accepting
only true/false/1/0 case-insensitively after stripping whitespace. Unrecognized
environment keys are ignored. If APP_TIMEOUT is supplied, create network when
missing, but reject an existing non-dictionary network with ValueError. An absent
environment key leaves the merged value unchanged. Do not read os.environ.

Execution requirements: create/update a plan; fully read both editable files;
run `python -m pytest -q` before the first write (initial failures are expected);
implement the fix; run the same full command after the last write; when it passes,
mark the plan done and finish normally with final_answer. Never edit tests.
