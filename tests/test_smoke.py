"""Smoke test: the pytest11 plugin loads and registers the testvibe markers.

This is the foundation acceptance test (Task A1). If the testvibe package is
installed and its pytest11 entry point resolves, ``pytest_configure`` runs and
registers the ``testvibe_scenario`` marker (among others). Without the plugin
loaded, the marker set is empty and this assertion fails.
"""


def test_plugin_loads(pytestconfig):
    # In pytest 8, ``getini("markers")`` returns a list of ``"name: desc"``
    # strings (NOT objects with ``.name``). Parse the leading token.
    markers = pytestconfig.getini("markers")
    names = {m.split(":", 1)[0].strip() for m in markers}
    assert "testvibe_scenario" in names
