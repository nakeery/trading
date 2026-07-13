"""
Black-Scholes / Merton implied volatility solver.

Used by backfill_iv.py to invert historical option prices (from Massive
aggregates) into implied volatilities for Phase 3 retraining.

All inputs/outputs use consistent units:
  - Prices in the same currency as the option (S, K, C, P)
  - Rates/yields as annual decimals  (r=0.05 → 5%)
  - Time in years                    (T=30/252 → ~30 trading days)
  - Volatility as annual decimal     (sigma=0.22 → 22%)
"""

import math


def _norm_cdf(x):
    """Standard normal CDF via math.erfc for numerical accuracy."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_pdf(x):
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes_call(S, K, r, T, sigma, q=0.0):
    """
    European call price via Merton (1973) with continuous dividend yield q.

    Args:
        S:     spot price
        K:     strike price
        r:     risk-free rate (annual decimal)
        T:     time to expiry (years)
        sigma: implied volatility (annual decimal)
        q:     continuous dividend yield (default 0)

    Returns:
        Theoretical call price
    """
    if T <= 0 or sigma <= 0:
        return max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    return (S * math.exp(-q * T) * _norm_cdf(d1)
            - K * math.exp(-r * T) * _norm_cdf(d2))


def vega(S, K, r, T, sigma, q=0.0):
    """
    Analytical vega (dC/d_sigma) — Newton-Raphson denominator.

    Returns dC/d_sigma (>= 0); zero when T <= 0 or sigma <= 0.
    """
    if T <= 0 or sigma <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return S * math.exp(-q * T) * _norm_pdf(d1) * math.sqrt(T)


def bs_delta(S, K, r, T, sigma, q=0.0, contract_type="call"):
    """
    Black-Scholes delta for locating 25-delta skew pairs.

    Args:
        contract_type: "call" (delta 0 to 1) or "put" (delta -1 to 0)

    Returns:
        Delta value
    """
    if T <= 0 or sigma <= 0:
        if contract_type == "call":
            return 1.0 if S > K else 0.0
        return -1.0 if S < K else 0.0
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    if contract_type == "call":
        return math.exp(-q * T) * _norm_cdf(d1)
    return -math.exp(-q * T) * _norm_cdf(-d1)


def bs_gamma(S, K, r, T, sigma, q=0.0):
    """
    Black-Scholes gamma (d²C/dS²) — identical for calls and puts. Used by modules/gex.py
    to re-price per-contract gamma at hypothetical spot levels for the zero-gamma flip.

    Returns gamma (per $1 of underlying move, per share); 0 when T/sigma/S are degenerate.
    """
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
    return math.exp(-q * T) * _norm_pdf(d1) / (S * sigma * math.sqrt(T))


def implied_vol(C, S, K, r, T, q=0.0, tol=1e-6, max_iter=100):
    """
    Call implied volatility via Newton-Raphson with bisection fallback.

    Args:
        C:        observed call price (mid-market or last trade)
        S:        spot price
        K:        strike
        r:        risk-free rate (annual decimal)
        T:        time to expiry (years)
        q:        continuous dividend yield (default 0)
        tol:      convergence tolerance on price difference
        max_iter: max Newton-Raphson iterations before bisection fallback

    Returns:
        Implied volatility (annual decimal, e.g. 0.22 for 22%)

    Raises:
        ValueError: price below intrinsic, T <= 0, or solver non-convergence
    """
    if T <= 0:
        raise ValueError("T must be > 0")
    intrinsic = max(S * math.exp(-q * T) - K * math.exp(-r * T), 0.0)
    if C < intrinsic - tol:
        raise ValueError(f"Call price {C:.4f} below intrinsic {intrinsic:.4f}")

    # Brenner-Subrahmanyam initial guess: sigma ~ sqrt(2*pi/T) * C/S
    sigma = math.sqrt(2 * math.pi / T) * C / S
    sigma = max(min(sigma, 10.0), 1e-4)

    # Newton-Raphson
    for _ in range(max_iter):
        price = black_scholes_call(S, K, r, T, sigma, q)
        v = vega(S, K, r, T, sigma, q)
        diff = price - C
        if abs(diff) < tol:
            return sigma
        if v < 1e-10:
            break  # flat vega — fall through to bisection
        sigma -= diff / v
        sigma = max(min(sigma, 10.0), 1e-4)

    # Bisection fallback
    lo, hi = 1e-4, 10.0
    if black_scholes_call(S, K, r, T, lo, q) > C:
        raise ValueError(f"Price below lo-bound BS value (C={C:.4f})")
    for _ in range(200):
        mid = (lo + hi) / 2
        if black_scholes_call(S, K, r, T, mid, q) < C:
            lo = mid
        else:
            hi = mid
        if hi - lo < tol:
            return (lo + hi) / 2

    raise ValueError(
        f"IV solver did not converge "
        f"(C={C:.4f}, S={S:.4f}, K={K:.4f}, T={T:.4f})"
    )


def implied_vol_put(P, S, K, r, T, q=0.0, **kwargs):
    """
    Put implied volatility via put-call parity -> call equivalent -> implied_vol().

    Put-call parity: C = P + S*exp(-qT) - K*exp(-rT)

    Args:
        P:  observed put price
        remaining args: same as implied_vol()

    Returns:
        Implied volatility (annual decimal)

    Raises:
        ValueError: same conditions as implied_vol()
    """
    C_synthetic = P + S * math.exp(-q * T) - K * math.exp(-r * T)
    C_synthetic = max(C_synthetic, 0.0)  # floor at 0 for deep OTM puts
    return implied_vol(C_synthetic, S, K, r, T, q, **kwargs)
