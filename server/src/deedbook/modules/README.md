# Modules activables

Chaque sous-dossier est un module qui déclare un `module.toml` :

```toml
[module]
name = "mon-module"
permissions = ["audit:read"]
functions = ["search", "export"]
menu = ["Recherche", "Exports"]
```

Un module n'est chargé que s'il figure dans `[modules] enabled` de
`deedbook.toml`. Inactif = ni chargé, ni exposé, ni affiché.
