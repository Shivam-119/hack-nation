"""Calibrate the builder evaluator against known strong founders.

Reference profiles (public knowledge):
- guillermo rauch (rauchg) — built Next.js, founded Vercel. $3.5B valuation.
- evan you (yyx990803) — created Vue.js solo, bootstrapped to mass adoption.
- george hotz (geohot) — built comma.ai (openpilot), tinygrad. Hacker legend.
- tiangolo — created FastAPI. Solo builder, massive adoption.
- piaborez (Pieter Levels / levelsio) — nomadlist, remoteok. Indie founder, ships fast.
- karpathy — Andrej Karpathy. Tesla AI director, built minGPT, nanoGPT.
- mitchellh — Mitchell Hashimoto. Founded HashiCorp ($5B+). Vagrant, Terraform.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from vc_brain.sourcing.github_evaluator import evaluate


REFERENCE_BUILDERS = [
    "rauchg",       # Guillermo Rauch — Vercel/Next.js
    "yyx990803",    # Evan You — Vue.js
    "geohot",       # George Hotz — comma.ai
    "tiangolo",     # Sebastian Ramirez — FastAPI
    "levelsio",     # Pieter Levels — nomadlist
    "karpathy",     # Andrej Karpathy — nanoGPT
    "mitchellh",    # Mitchell Hashimoto — HashiCorp
]


async def main():
    for username in REFERENCE_BUILDERS:
        print(f"\n{'='*70}")
        try:
            result = await evaluate(username)
            print(f"  {username} — Grade: {result.grade} | Score: {result.score}/100 | Builder: {result.is_builder}")
            print(f"  Shipping: {result.shipping} | Consistency: {result.consistency} | Validation: {result.validation} | Communication: {result.communication}")
            print(f"  Signals:")
            for s in result.signals:
                print(f"    + {s}")
            print(f"  Red Flags:")
            if result.red_flags:
                for r in result.red_flags:
                    print(f"    - {r}")
            else:
                print(f"    (none)")
        except Exception as e:
            print(f"  {username} — ERROR: {e}")
        print(f"{'='*70}")


if __name__ == "__main__":
    asyncio.run(main())
