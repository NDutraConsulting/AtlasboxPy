from atlasboxpy_db import VariantRouter


def test_no_label_resolves_to_default():
    router = VariantRouter(name="kanban-db", default="prod", variants={"shadow": "shadow-db"})
    assert router.resolve(None) == "prod"


def test_matching_label_resolves_to_its_variant():
    router = VariantRouter(name="kanban-db", default="prod", variants={"shadow": "shadow-db"})
    assert router.resolve("shadow") == "shadow-db"


def test_unrecognized_label_falls_back_to_default_not_an_error():
    router = VariantRouter(name="kanban-db", default="prod", variants={"shadow": "shadow-db"})
    assert router.resolve("prod") == "prod"
    assert router.resolve("nonexistent") == "prod"
    assert router.resolve("") == "prod"
    assert router.resolve("' OR 1=1 --") == "prod"


def test_no_variants_registered_everything_resolves_to_default():
    router = VariantRouter(name="kanban-db", default="prod", variants={})
    assert router.resolve(None) == "prod"
    assert router.resolve("shadow") == "prod"


def test_resolved_label_reports_which_variant_actually_matched():
    router = VariantRouter(name="kanban-db", default="prod", variants={"shadow": "shadow-db"})
    assert router.resolved_label(None) == "default"
    assert router.resolved_label("nonexistent") == "default"
    assert router.resolved_label("shadow") == "shadow"


def test_multiple_variants_each_resolve_independently():
    router = VariantRouter(
        name="kanban-db",
        default="prod",
        variants={"shadow": "shadow-db", "staging": "staging-db"},
    )
    assert router.resolve("shadow") == "shadow-db"
    assert router.resolve("staging") == "staging-db"
    assert router.resolve("prod") == "prod"
