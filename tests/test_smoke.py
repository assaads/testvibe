"""Smoke test: the pytest11 plugin loads and registers the testvibe markers.

This is the foundation acceptance test (Task A1). If the testvibe package is
installed and its pytest11 entry point resolves, ``pytest_configure`` runs and
registers the ``testvibe_scenario`` marker (among others). Without the plugin
loaded, the marker set is empty and this assertion fails.
"""


def test_plugin_loads(pytestconfig):
    # In pytest 8, ``getini("markers")`` returns a list of ``"name: desc"``
    # strings (NOT objects with ``.name``). Parse defensively so this works
    # whether entries are bare strings or MarkValidator objects.
    import testvibe.plugin

    names = set()
    for m in pytestconfig.getini("markers"):
        names.add(getattr(m, "name", None) or str(m).split(":", 1)[0].strip())
    assert set(testvibe.plugin.MARKERS) <= names


def test_console_script_entry_point():
    from importlib.metadata import entry_points

    eps = entry_points(group="console_scripts")
    tv = [e for e in eps if e.name == "testvibe"]
    assert tv, "testvibe console_scripts entry point missing"
    assert tv[0].value == "testvibe.cli:main"
