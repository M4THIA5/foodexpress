#!/usr/bin/env bash
#
# demo.sh — scénario de démonstration du prototype FoodExpress.
#
# Rejoue automatiquement, à travers l'API Gateway (auth mockée + reverse-proxy),
# les quatre parcours déterministes qui exercent la SAGA orchestrée et ses
# compensations. Chaque parcours affiche la requête, l'état final de la commande
# et la trace `saga_steps`, puis vérifie l'état attendu (✓/✗).
#
#   1. Commande OK   — chemin nominal .......................... CONFIRMED
#   2. Paiement KO   — montant ≥ seuil PSP (compensation) ...... CANCELLED
#   3. Livraison KO  — restaurant hors zone (compensation) ..... CANCELLED
#   4. Refus resto   — restaurant fermé (échec amont) .......... CANCELLED
#
# Le Circuit Breaker (Commande → Paiement) se démontre à la main : voir docs/demo.md.
#
# Prérequis : la stack tourne (`docker compose up --build`). Aucune dépendance
# autre que curl + python3 (jq utilisé seulement s'il est présent, pour la couleur).
#
# Code de sortie 0 si toutes les assertions passent, 1 sinon (sert de smoke-test).

set -u

GW_ROOT="${GW_ROOT:-http://127.0.0.1:8000}"
BASE="$GW_ROOT/api/v1"
TOKEN="${TOKEN:-demo-token}"          # tout Bearer non vide est accepté (auth mockée)
CLIENT_ID=42
POLL_MAX=30                            # secondes max d'attente de la boucle async RabbitMQ

# ---- présentation (couleurs seulement en TTY) -------------------------------
if [ -t 1 ]; then
  BOLD=$'\033[1m'; DIM=$'\033[2m'; RED=$'\033[31m'; GRN=$'\033[32m'
  YEL=$'\033[33m'; CYA=$'\033[36m'; RST=$'\033[0m'
else
  BOLD=; DIM=; RED=; GRN=; YEL=; CYA=; RST=
fi

FAILURES=0
RESP_CODE=; RESP_BODY=

section() { printf '\n%s\n%s %s%s\n' "${BOLD}────────────────────────────────────────────────────────${RST}" \
  "${BOLD}${CYA}▶${RST}" "${BOLD}$*${RST}" ""; }
info()    { printf '  %s%s%s\n' "${DIM}" "$*" "${RST}"; }

# ---- appel HTTP : remplit RESP_CODE / RESP_BODY -----------------------------
api_call() {
  local method="$1" path="$2" data="${3:-}" out
  if [ -n "$data" ]; then
    out=$(curl -s -w $'\n%{http_code}' -X "$method" "$BASE$path" \
      -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "$data")
  else
    out=$(curl -s -w $'\n%{http_code}' -X "$method" "$BASE$path" \
      -H "Authorization: Bearer $TOKEN")
  fi
  RESP_CODE="${out##*$'\n'}"
  RESP_BODY="${out%$'\n'*}"
}

# ---- extraction d'un champ JSON (python3, garanti — pas de dépendance jq) ----
jget() { printf '%s' "$1" | python3 -c 'import sys,json
d=json.load(sys.stdin)
for k in sys.argv[1].split("."):
    d = d[int(k)] if k.lstrip("-").isdigit() else d.get(k)
print("" if d is None else d)' "$2" 2>/dev/null; }

# ---- affiche la trace SAGA d'une réponse commande ---------------------------
print_saga() {
  printf '%s' "$1" | python3 -c 'import sys,json
o=json.load(sys.stdin)
for s in o.get("saga_steps",[]):
    p=(" — "+s["payload"]) if s.get("payload") else ""
    print("      %-24s %-12s%s" % (s["etape"], s["statut"], p))' 2>/dev/null
}

# ---- passe une commande : place_order <restaurant_id> <items_json> ----------
place_order() {
  api_call POST /orders "{\"client_id\":$CLIENT_ID,\"restaurant_id\":$1,\"items\":$2}"
}

# ---- interroge la commande jusqu'à un état terminal (boucle async) ----------
poll_terminal() {
  local id="$1" i statut
  for ((i = 0; i < POLL_MAX; i++)); do
    api_call GET "/orders/$id"
    statut="$(jget "$RESP_BODY" statut)"
    case "$statut" in
      CONFIRMED|CANCELLED) printf '%s' "$statut"; return 0 ;;
    esac
    sleep 1
  done
  printf 'TIMEOUT(%s)' "$statut"
}

# ---- assertion : compare état attendu et obtenu -----------------------------
assert_status() {
  local expected="$1" actual="$2"
  if [ "$expected" = "$actual" ]; then
    printf '  %s✓ attendu %s — obtenu %s%s\n' "${GRN}${BOLD}" "$expected" "$actual" "${RST}"
  else
    printf '  %s✗ attendu %s — obtenu %s%s\n' "${RED}${BOLD}" "$expected" "$actual" "${RST}"
    FAILURES=$((FAILURES + 1))
  fi
}

# ---- vérifie que la stack répond avant de lancer les scénarios --------------
preflight() {
  section "Préflight — la stack répond ?"
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "$GW_ROOT/health")" != "200" ]; then
    printf '  %sGateway injoignable sur %s.%s\n' "$RED" "$GW_ROOT" "$RST"
    printf '  Lance la stack : %sdocker compose up --build%s\n' "$BOLD" "$RST"
    exit 1
  fi
  api_call GET /restaurants/1/menu
  if [ "$RESP_CODE" != "200" ]; then
    printf '  %sRestaurant amont pas prêt (HTTP %s) — attends le démarrage complet.%s\n' \
      "$RED" "$RESP_CODE" "$RST"
    exit 1
  fi
  info "Gateway OK · Restaurant seedé ($(jget "$RESP_BODY" restaurant.nom))"
}

# ================================ SCÉNARIOS ==================================

# Restaurant 1 (Chez Luigi) : ouvert, plats disponibles, zone couverte.
scenario_ok() {
  section "SCÉNARIO 1 — Commande OK (chemin nominal SAGA)"
  info "Resto 1 · plats 11+12 (24,50 €) · attend la boucle RabbitMQ DeliveryAssigned"
  place_order 1 '[{"plat_id":11,"quantite":1},{"plat_id":12,"quantite":1}]'
  local id total; id="$(jget "$RESP_BODY" id)"; total="$(jget "$RESP_BODY" montant_total)"
  info "POST /orders → HTTP $RESP_CODE · id=$id · total=$total € · statut initial=$(jget "$RESP_BODY" statut)"
  local final; final="$(poll_terminal "$id")"
  api_call GET "/orders/$id"; print_saga "$RESP_BODY"
  assert_status CONFIRMED "$final"
}

# Restaurant 1 mais montant ≥ 1000 € : le PSP refuse (402) → compensation resto.
scenario_paiement_ko() {
  section "SCÉNARIO 2 — Paiement KO (refus PSP + compensation)"
  info "Resto 1 · plat 11 ×90 (1035 € ≥ seuil 1000) · Paiement DECLINED → Restaurant.cancel"
  place_order 1 '[{"plat_id":11,"quantite":90}]'
  local id; id="$(jget "$RESP_BODY" id)"
  info "POST /orders → HTTP $RESP_CODE · id=$id · total=$(jget "$RESP_BODY" montant_total) €"
  local final; final="$(poll_terminal "$id")"
  api_call GET "/orders/$id"; print_saga "$RESP_BODY"
  assert_status CANCELLED "$final"
}

# Restaurant 2 (Sushi Zen) : ouvert mais hors zone livreur → DeliveryFailed.
scenario_livraison_ko() {
  section "SCÉNARIO 3 — Livraison KO (hors zone + compensation)"
  info "Resto 2 · plat 21 (14,90 €) · resto accepte, paiement débité, PUIS échec livraison"
  info "→ compensation : Paiement.refund + Restaurant.cancel"
  place_order 2 '[{"plat_id":21,"quantite":1}]'
  local id; id="$(jget "$RESP_BODY" id)"
  info "POST /orders → HTTP $RESP_CODE · id=$id · statut initial=$(jget "$RESP_BODY" statut)"
  local final; final="$(poll_terminal "$id")"
  api_call GET "/orders/$id"; print_saga "$RESP_BODY"
  assert_status CANCELLED "$final"
}

# Restaurant 3 (Le Bistrot Fermé) : actif=False → refus déterministe (409 interne).
scenario_refus_resto() {
  section "SCÉNARIO 4 — Refus restaurant (échec amont synchrone)"
  info "Resto 3 (fermé) · plat 31 · Restaurant refuse → SAGA annule sans débit"
  place_order 3 '[{"plat_id":31,"quantite":1}]'
  local id; id="$(jget "$RESP_BODY" id)"
  info "POST /orders → HTTP $RESP_CODE · id=$id · statut=$(jget "$RESP_BODY" statut)"
  print_saga "$RESP_BODY"
  assert_status CANCELLED "$(jget "$RESP_BODY" statut)"
}

# =============================================================================
main() {
  printf '%s\n' "${BOLD}${YEL}FoodExpress — scénario de démonstration du prototype${RST}"
  printf '%sGateway : %s · préfixe /api/v1 · auth Bearer mockée%s\n' "$DIM" "$GW_ROOT" "$RST"
  preflight
  scenario_ok
  scenario_paiement_ko
  scenario_livraison_ko
  scenario_refus_resto

  section "Bilan"
  if [ "$FAILURES" -eq 0 ]; then
    printf '  %s✓ Tous les scénarios ont produit l’état attendu.%s\n' "${GRN}${BOLD}" "$RST"
    printf '  %sDémo bonus — Circuit Breaker : voir docs/demo.md (§5).%s\n\n' "$DIM" "$RST"
    exit 0
  fi
  printf '  %s✗ %d scénario(s) en échec.%s\n\n' "${RED}${BOLD}" "$FAILURES" "$RST"
  exit 1
}

main "$@"
