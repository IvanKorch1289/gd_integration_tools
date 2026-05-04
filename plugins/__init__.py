"""Корневой пакет плагинов проекта (in-tree).

Плагины из этой директории загружаются через
``PluginLoader.load_from_path("plugins/<name>")`` (см. Wave 4).
Внешние плагины-дистрибутивы регистрируются через
``importlib.metadata.entry_points``.
"""
