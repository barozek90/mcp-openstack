# mcp-openstack

Serwer MCP dla OpenStack z **bezpiecznikami na poziomie serwera** (read-only by default).

Wrapper na [`python-openstackmcp-server`](https://github.com/openstack-kr/python-openstackmcp-server)
(FastMCP + openstacksdk) z middleware polityki: filtrowaniem narzędzi (`tools/list`)
i twardym blokowaniem wywołań (`tools/call`) — niezależnie od klienta MCP
(opencode, Claude Code, itd.).

## Szybki start

```bash
uv sync
uv run pytest          # testy
uv run mcp-openstack   # serwer (stdio)
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
- Polityka: `~/.config/mcp-openstack/policy.yaml` (override: env `OS_MCP_GUARD_POLICY`)

```yaml
mode: read-only        # read-only | custom
allow:                 # globy fnmatch, tylko tryb custom
  - "get_*"
  - "set_cloud_name"
deny: []               # wygrywa z allow
```

## Listowanie per projekt / user / wszystkie projekty (admin)

Bez argumentów `get_*` listują to samo co wcześniej (Nova, Cinder, Designate i Heat
tylko projekt z tokena, Neutron wszystko, co widzi admin). Na konto admina dochodzą
opcjonalne parametry:

| Parametr | Znaczenie | Gdzie |
|---|---|---|
| `project` | nazwa **albo** ID projektu | serwery, wolumeny, załączniki, sieci/subnety/porty/routery/SG/floating IP, obrazy (właściciel), LB/listenery/pule/health monitory, strefy i recordsety DNS, stacki Heat, server groups |
| `user` | nazwa albo ID usera | serwery, wolumeny, keypairs |
| `all_projects` | zasoby wszystkich projektów | serwery, wolumeny, załączniki, strefy i recordsety DNS, stacki Heat, server groups |
| `limit` | maks. liczba elementów (domyślnie 5000, `0` = bez limitu) | wszystkie powyższe |

Nowe narzędzie `get_users` (filtry `name`, `domain_id`, `enabled`) pomaga znaleźć usera;
`get_projects` ma filtry `name`, `domain_id`, `parent_id`, `enabled`. Starsze `project_id`
w `get_subnets`, `get_routers`, `get_security_groups` i `get_floating_ips` nadal działa
(tylko ID). `get_compute_quotas` i `get_dns_quota` przyjmują w `project_id` także nazwę.

Wynik narzędzi z tej listy to obwiednia:

```json
{"total": 120, "returned": 100, "truncated": true, "limit": 100, "items": [ ... ]}
```

`total` to liczba wszystkich pasujących zasobów, `items` jest ucinane do `limit`.
Elementy listy serwerów i wolumenów mają `project_id`, `user_id` oraz hosta
(`compute_host`/`hypervisor_hostname`, `host`), a LB, listenery, pule i health monitory
mają `project_id`.

Przykłady (argumenty wywołania narzędzia):

```text
get_servers   {"project": "EXAMPLE-PROJECT"}
get_servers   {"all_projects": true, "status": "ERROR", "limit": 50}
get_volumes   {"user": "tester"}
get_dns_zones {"all_projects": true}
get_networks  {"project": "EXAMPLE-PROJECT"}
```

Uwagi: `project`/`user`/`all_projects` wymagają uprawnień admina po stronie chmury;
nazwa projektu jest rozwiązywana przez Keystone (niejednoznaczna lub nieznana nazwa
kończy się błędem). Stacki Heat spoza własnego projektu są listowane przez
`global_tenant`; gdy chmura tego zabrania (polityka `stacks:global_index`), narzędzie
zwraca zwykłą listę Heat (dla admina bywa, że obejmuje już inne projekty), filtruje ją
po `project` i dodaje do wyniku pole `note`.

Pełna dokumentacja: `../openstack-mcp-setup.md`.
