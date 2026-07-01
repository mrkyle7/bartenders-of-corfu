"""Fit the lookahead evaluator's weights from real game history.

Instead of hand-guessing the weights in ``EvalWeights``, learn them: replay ended
games from the public API, and for many mid/late-game states label each active
player by whether they went on to **win**. A logistic regression on the evaluator
feature decomposition (``evaluator.player_features``) then recovers the weight of
each term — including the whole drunk/bladder penalty curve (one-hot per level)
and how much *cocktails* actually matter (the ``cocktail`` feature), straight from
what wins real games.

The fit is normalised so ``points`` == 1.0 (the points-equivalent scale the rest
of ``evaluate`` assumes), mapped back to an ``EvalWeights`` via
``evaluator.weights_from_coefficients``, and printed as a ready-to-paste literal.
Gate it with the gauntlet before shipping — this only proposes weights.

Usage:
    uv run python -m ml.fit_evaluator --games 50 --samples 10
    uv run python -m ml.fit_evaluator --out /tmp/fitted.json   # also save JSON
"""

import argparse
import json
import urllib.request

import numpy as np

from app.GameState import GameState

from ml.evaluator import (
    DEFAULT_WEIGHTS,
    FEATURE_NAMES,
    player_features,
    weights_from_coefficients,
)

DEFAULT_URL = "https://cheetahmoongames.com"


def _fetch(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def fetch_ended_games(base_url: str, max_games: int) -> list[dict]:
    games: list[dict] = []
    page = 1
    while len(games) < max_games:
        data = _fetch(f"{base_url}/v1/games?status=ENDED&page={page}&page_size=100")
        batch = data.get("games", [])
        if not batch:
            break
        games.extend(batch)
        if len(batch) < 100:
            break
        page += 1
    return games[:max_games]


def _sample_turns(max_turn: int, n: int) -> list[int]:
    """Evenly spaced turns across the mid-to-late game (position predicts outcome)."""
    if max_turn < 4:
        return []
    lo, hi = int(max_turn * 0.25), int(max_turn * 0.95)
    if hi <= lo:
        return [max_turn // 2]
    return sorted({int(round(t)) for t in np.linspace(lo, hi, n)})


def build_dataset(
    base_url: str, games: list[dict], samples_per_game: int, verbose: bool
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return (X, y, n_games_used): features and win-labels over sampled states."""
    rows: list[list[float]] = []
    labels: list[float] = []
    used = 0
    for gi, game in enumerate(games):
        state = game.get("game_state") or {}
        winner = state.get("winner")
        if not winner:
            continue
        gid = game["id"]
        max_turn = state.get("turn_number", 0)
        turns = _sample_turns(max_turn, samples_per_game)
        got = 0
        for t in turns:
            try:
                snap = _fetch(f"{base_url}/v1/games/{gid}/history/{t}")["game_state"]
                gs = GameState.from_dict(snap)
            except Exception:
                continue
            for pid, ps in gs.player_states.items():
                if ps.is_eliminated:
                    # An eliminated player didn't win; still a useful negative.
                    label = 0.0
                else:
                    label = 1.0 if str(pid) == str(winner) else 0.0
                feats = player_features(gs, ps)
                rows.append([feats[name] for name in FEATURE_NAMES])
                labels.append(label)
                got += 1
        if got:
            used += 1
        if verbose and (gi + 1) % 10 == 0:
            print(f"  processed {gi + 1}/{len(games)} games, {len(rows)} samples")
    return np.array(rows, dtype=float), np.array(labels, dtype=float), used


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30, 30)))


def fit_logistic(
    X: np.ndarray, y: np.ndarray, l2: float, iters: int, lr: float
) -> tuple[dict[str, float], float]:
    """Standardised logistic regression → raw per-feature coefficients + train AUC.

    Coefficients are returned on the *raw* feature scale (un-standardised) and
    normalised so ``points`` == 1.0. The intercept is discarded (it doesn't affect
    action selection, which is argmax over states).
    """
    mu = X.mean(axis=0)
    sigma = X.std(axis=0)
    sigma[sigma == 0] = 1.0
    Xs = (X - mu) / sigma
    n, d = Xs.shape
    Xb = np.hstack([np.ones((n, 1)), Xs])  # intercept column 0
    w = np.zeros(d + 1)
    for _ in range(iters):
        p = _sigmoid(Xb @ w)
        grad = Xb.T @ (p - y) / n
        grad[1:] += l2 * w[1:]  # L2 on features, not intercept
        w -= lr * grad

    coef_std = w[1:]
    coef_raw = coef_std / sigma
    points_idx = FEATURE_NAMES.index("points")
    scale = coef_raw[points_idx]
    if scale <= 1e-9:
        raise SystemExit(
            "points did not come out positive — not enough signal to fit "
            f"(points coef = {scale:.4g}). Try more games/samples."
        )
    coef_norm = coef_raw / scale
    coef = {name: float(coef_norm[i]) for i, name in enumerate(FEATURE_NAMES)}

    # Train AUC as a sanity check on the fit.
    scores = Xb @ w
    auc = _auc(scores, y)
    return coef, auc


def _auc(scores: np.ndarray, y: np.ndarray) -> float:
    pos = scores[y == 1]
    neg = scores[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    # Mann–Whitney U via ranking.
    order = np.argsort(scores)
    ranks = np.empty_like(order, dtype=float)
    ranks[order] = np.arange(1, len(scores) + 1)
    r_pos = ranks[y == 1].sum()
    return float((r_pos - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def _format_weights(w) -> str:
    return (
        "EvalWeights(\n"
        f"    points={w.points:.4f},\n"
        f"    karaoke_card={w.karaoke_card:.4f},\n"
        f"    near_karaoke_win={w.near_karaoke_win:.4f},\n"
        f"    cup_sell={w.cup_sell:.4f},\n"
        f"    special_mat={w.special_mat:.4f},\n"
        f"    specialist={w.specialist:.4f},\n"
        f"    doubler={w.doubler:.4f},\n"
        f"    store={w.store:.4f},\n"
        f"    refresher={w.refresher:.4f},\n"
        f"    cup_progress={w.cup_progress:.4f},\n"
        f"    threshold={w.threshold:.4f},\n"
        f"    cocktail_progress={w.cocktail_progress:.4f},\n"
        f"    drunk_penalty={tuple(round(x, 4) for x in w.drunk_penalty)},\n"
        "    bladder_penalty_by_room="
        f"{tuple(round(x, 4) for x in w.bladder_penalty_by_room)},\n"
        ")"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Fit evaluator weights from history")
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--games", type=int, default=50)
    ap.add_argument("--samples", type=int, default=10, help="states sampled per game")
    ap.add_argument("--l2", type=float, default=0.02)
    ap.add_argument("--iters", type=int, default=4000)
    ap.add_argument("--lr", type=float, default=0.3)
    ap.add_argument("--out", default=None, help="optional JSON path for the coefs")
    ap.add_argument(
        "--fit-safety",
        action="store_true",
        help="also USE the fitted drunk/bladder curve. Off by default: winners are "
        "drunk because they drink productively, so the correlational fit rewards "
        "drunkenness — suicidal for action selection. By default the one-hots are "
        "kept in the fit as *controls* (de-confounding the value terms) but the "
        "hand-tuned convex safety penalties are used in the output.",
    )
    args = ap.parse_args()

    print(f"Fetching ended games from {args.url} ...")
    games = fetch_ended_games(args.url, args.games)
    print(f"  {len(games)} ended games")
    print("Building dataset (this fetches per-turn states) ...")
    X, y, used = build_dataset(args.url, games, args.samples, verbose=True)
    print(f"  {len(y)} samples from {used} games, win rate {y.mean():.3f}")
    if len(y) < 50:
        raise SystemExit("Too few samples to fit — increase --games/--samples.")

    coef, auc = fit_logistic(X, y, args.l2, args.iters, args.lr)

    if not args.fit_safety:
        # Keep the causal, convex hand-tuned safety curve; overwrite the fitted
        # (correlational, inverted) safety coefs so the mapping/JSON reconstruct it.
        for lvl in range(1, 6):
            coef[f"drunk_{lvl}"] = -DEFAULT_WEIGHTS.drunk_penalty[lvl]
        for r in range(4):
            coef[f"bladder_room_{r}"] = -DEFAULT_WEIGHTS.bladder_penalty_by_room[r]

    weights = weights_from_coefficients(coef)

    print(f"\nTrain AUC (position → win): {auc:.3f}\n")
    print("Fitted weights (points-normalised):")
    for name in FEATURE_NAMES:
        print(f"  {name:<16} {coef[name]:+.4f}")
    print("\nAs EvalWeights (paste into ml/versions.py to gauntlet):\n")
    print(_format_weights(weights))

    if args.out:
        with open(args.out, "w") as fh:
            json.dump(coef, fh, indent=2)
        print(f"\nSaved coefficients to {args.out}")


if __name__ == "__main__":
    main()
