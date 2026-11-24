# openstack-mcp-guarded

Serwer MCP dla OpenStack z **bezpiecznikami na poziomie serwera** (read-only by default).

Wrapper na [`python-openstackmcp-server`](https://github.com/openstack-kr/python-openstackmcp-server)
(FastMCP + openstacksdk) z middleware polityki: filtrowaniem narzędzi (`tools/list`)
i twardym blokowaniem wywołań (`tools/call`) — niezależnie od klienta MCP
(opencode, Claude Code, itd.).

## Szybki start

```bash
uv sync
uv run pytest          # testy
uv run openstack-mcp-guarded   # serwer (stdio)
```

## Konfiguracja

- Chmury: standardowy `~/.config/openstack/clouds.yaml` (multi-cloud, przełączanie narzędziem `set_cloud_name`)
- Katalog z konfiguracją: env `OS_MCP_GUARD_CONFIG_DIR=/ścieżka/do/katalogu` — serwer
  szuka w nim `clouds.yaml` (wymagany) i `secure.yaml` (opcjonalny, ostrzeżenie gdy
  dostępny dla grupy/innych) i mapuje je na `OS_CLIENT_CONFIG_FILE` /
  `OS_CLIENT_SECURE_FILE` (zmienne ustawione jawnie mają pierwszeństwo).
  Zmienna jest zużywana przy starcie, żeby openstacksdk nie utworzył fikcyjnej chmury `envvars`.
- Chmura startowa: env `CLOUD_NAME` (nazwa dopasowywana bez rozróżniania wielkości liter;
  uwaga: serwer nie czyta `OS_CLOUD`).
- Polityka: `~/.config/openstack-mcp-guarded/policy.yaml` (override: env `OS_MCP_GUARD_POLICY`)

```yaml
mode: read-only        # read-only | custom
allow:                 # globy fnmatch, tylko tryb custom
  - "get_*"
  - "set_cloud_name"
deny: []               # wygrywa z allow
```

Pełna dokumentacja: `../openstack-mcp-setup.md`.
