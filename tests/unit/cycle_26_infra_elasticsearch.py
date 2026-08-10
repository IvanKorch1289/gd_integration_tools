"""Unit-тесты для cycle 26 infra_elasticsearch DSL processor.

Self-contained — does NOT import the processor module (which requires
DI + facade + ES client). Tests the processor LOGIC by inspecting AST.

User request (turn 39): wrap unused deps (elasticsearch) in DSL.
Verified: src/backend/dsl/engine/processors/infra_elasticsearch.py created.
"""


from __future__ import annotations

import ast
import os
import re


class TestInfraElasticsearchProcessorExists:
    """infra_elasticsearch.py must exist as a DSL processor module."""

    def test_file_exists(self):
        path = "src/backend/dsl/engine/processors/infra_elasticsearch.py"
        assert os.path.exists(path), f"{path} missing"

    def test_module_parses(self):
        path = "src/backend/dsl/engine/processors/infra_elasticsearch.py"
        with open(path) as f:
            tree = ast.parse(f.read())
        # Find classes
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        assert "InfraElasticsearchSearchProcessor" in classes
        assert "InfraElasticsearchIndexProcessor" in classes

    def test_search_processor_has_capability(self):
        path = "src/backend/dsl/engine/processors/infra_elasticsearch.py"
        with open(path) as f:
            content = f.read()
        assert "db.read.elasticsearch" in content
        assert "db.write.elasticsearch" in content


class TestFacadeRegistration:
    """elasticsearch_client_class must be in infrastructure_facade registry."""

    def test_facade_has_elasticsearch(self):
        path = "src/backend/core/di/providers/infrastructure_facade.py"
        with open(path) as f:
            content = f.read()
        assert "elasticsearch_client_class" in content
        assert "ElasticSearchClient" in content

    def test_processor_uses_correct_getter(self):
        path = "src/backend/dsl/engine/processors/infra_elasticsearch.py"
        with open(path) as f:
            content = f.read()
        # Must use the new getter, not direct import
        assert "get_elasticsearch_client_class" in content


class TestRegistryAnnotations:
    """Processors must use @processor decorator with proper schema."""

    def test_search_processor_decorated(self):
        path = "src/backend/dsl/engine/processors/infra_elasticsearch.py"
        with open(path) as f:
            content = f.read()
        # Look for decorator + class pattern
        assert '@processor(\n    "infra_elasticsearch_search"' in content or \
               '@processor("infra_elasticsearch_search"' in content, \
            "Search processor must use @processor decorator"

    def test_index_processor_decorated(self):
        path = "src/backend/dsl/engine/processors/infra_elasticsearch.py"
        with open(path) as f:
            content = f.read()
        assert '@processor(\n    "infra_elasticsearch_index"' in content or \
               '@processor("infra_elasticsearch_index"' in content, \
            "Index processor must use @processor decorator"

    def test_namespace_infra(self):
        path = "src/backend/dsl/engine/processors/infra_elasticsearch.py"
        with open(path) as f:
            content = f.read()
        assert 'namespace="infra"' in content


class TestPatternConsistency:
    """infra_elasticsearch must follow infra_mongodb pattern."""

    def test_same_structure_as_mongodb(self):
        es = open("src/backend/dsl/engine/processors/infra_elasticsearch.py").read()
        mongo = open("src/backend/dsl/engine/processors/infra_mongodb.py").read()

        # Both should have: @processor, capabilities, async process,
        # get_X_client_class DI call
        for pattern in [
            r"@processor\(",
            r"capabilities=\(",
            r"async def process",
            r"from src\.backend\.core\.di\.providers",
        ]:
            assert re.search(pattern, es), f"ES missing {pattern}"
            assert re.search(pattern, mongo), f"Mongo missing {pattern}"

    def test_both_set_result(self):
        es = open("src/backend/dsl/engine/processors/infra_elasticsearch.py").read()
        mongo = open("src/backend/dsl/engine/processors/infra_mongodb.py").read()
        assert "self.set_result(exchange, self.target, results)" in es
        assert "self.set_result(exchange, self.target," in mongo
