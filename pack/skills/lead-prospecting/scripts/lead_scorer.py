#!/usr/bin/env python3
"""
lead_scorer.py — B2B 리드 BANT 가중 점수 계산기

사용법:
    python3 lead_scorer.py --b 4 --a 3 --n 5 --t 2
    python3 lead_scorer.py --b 4 --a 3 --n 5 --t 2 --signal 1
    python3 lead_scorer.py  # 대화형 입력 모드

가중치 (SKILL.md 및 bant-evaluation.md와 동일):
    Budget   (B): 30%
    Authority(A): 25%
    Need     (N): 30%
    Timeline (T): 15%
    시그널 보너스:  +10% (--signal 1 시 적용, 1회만)

점수 범위: 0~100
등급 기준:
    고(高): 70점 이상
    중(中): 40~69점
    저(低): 40점 미만
"""

import argparse
import sys

# ── 가중치 상수 (SKILL.md·템플릿과 반드시 일치) ──────────────────────────
WEIGHT_B = 0.30   # Budget
WEIGHT_A = 0.25   # Authority
WEIGHT_N = 0.30   # Need
WEIGHT_T = 0.15   # Timeline
SIGNAL_BONUS_RATE = 0.10  # 시그널 보너스 (가중 합산 점수의 10%)

SCORE_MIN = 1
SCORE_MAX = 5

GRADE_HIGH_THRESHOLD = 70
GRADE_MID_THRESHOLD  = 40


def validate_score(value: str, label: str) -> int:
    """1~5 범위 정수로 변환하고 범위를 검증한다."""
    try:
        score = int(value)
    except ValueError:
        print(f"오류: {label} 점수는 정수여야 합니다 (입력값: {value!r})", file=sys.stderr)
        sys.exit(1)
    if not (SCORE_MIN <= score <= SCORE_MAX):
        print(
            f"오류: {label} 점수는 {SCORE_MIN}~{SCORE_MAX} 범위여야 합니다 (입력값: {score})",
            file=sys.stderr,
        )
        sys.exit(1)
    return score


def validate_signal(value: str) -> int:
    """0 또는 1을 검증한다."""
    try:
        signal = int(value)
    except ValueError:
        print(f"오류: --signal 값은 0 또는 1이어야 합니다 (입력값: {value!r})", file=sys.stderr)
        sys.exit(1)
    if signal not in (0, 1):
        print(f"오류: --signal 값은 0 또는 1이어야 합니다 (입력값: {signal})", file=sys.stderr)
        sys.exit(1)
    return signal


def compute_score(b: int, a: int, n: int, t: int, signal: int) -> dict:
    """
    BANT 점수를 받아 가중 합산 점수, 등급, 세부 내역을 반환한다.

    매개변수:
        b, a, n, t : 각 항목 점수 (1~5)
        signal     : 시그널 보너스 적용 여부 (0 또는 1)

    반환:
        dict {
            'weighted_raw': float,  # 보너스 전 가중 합산 (0~100 스케일)
            'bonus'       : float,  # 시그널 보너스 점수
            'total'       : float,  # 최종 점수 (0~100, 소수점 1자리)
            'grade'       : str,    # '고' / '중' / '저'
            'breakdown'   : dict,   # 항목별 기여 점수
        }
    """
    # 각 항목을 0~100 스케일로 정규화한 뒤 가중치 적용
    scale = (SCORE_MAX - SCORE_MIN)  # = 4

    b_norm = (b - SCORE_MIN) / scale * 100
    a_norm = (a - SCORE_MIN) / scale * 100
    n_norm = (n - SCORE_MIN) / scale * 100
    t_norm = (t - SCORE_MIN) / scale * 100

    b_contrib = b_norm * WEIGHT_B
    a_contrib = a_norm * WEIGHT_A
    n_contrib = n_norm * WEIGHT_N
    t_contrib = t_norm * WEIGHT_T

    weighted_raw = b_contrib + a_contrib + n_contrib + t_contrib
    bonus = weighted_raw * SIGNAL_BONUS_RATE if signal else 0.0
    total = min(weighted_raw + bonus, 100.0)

    if total >= GRADE_HIGH_THRESHOLD:
        grade = "고(高)"
    elif total >= GRADE_MID_THRESHOLD:
        grade = "중(中)"
    else:
        grade = "저(低)"

    return {
        "weighted_raw": round(weighted_raw, 1),
        "bonus": round(bonus, 1),
        "total": round(total, 1),
        "grade": grade,
        "breakdown": {
            "B (Budget)":    round(b_contrib, 1),
            "A (Authority)": round(a_contrib, 1),
            "N (Need)":      round(n_contrib, 1),
            "T (Timeline)":  round(t_contrib, 1),
        },
    }


def interactive_input() -> tuple:
    """대화형 모드: 사용자에게 BANT 점수를 입력받는다."""
    print("=" * 50)
    print("  lead_scorer.py — 대화형 입력 모드")
    print("  각 항목에 1~5 점수를 입력하세요.")
    print("  정보가 없는 항목은 '추가 조사 필요'로 표시하고")
    print("  이 도구 대신 bant-evaluation.md에 기록하세요.")
    print("=" * 50)

    def prompt(label):
        while True:
            raw = input(f"  {label} 점수 (1~5): ").strip()
            try:
                val = int(raw)
                if SCORE_MIN <= val <= SCORE_MAX:
                    return val
                print(f"  → {SCORE_MIN}~{SCORE_MAX} 범위의 정수를 입력하세요.")
            except ValueError:
                print("  → 정수를 입력하세요.")

    b = prompt("Budget   (B)")
    a = prompt("Authority(A)")
    n = prompt("Need     (N)")
    t = prompt("Timeline (T)")

    while True:
        raw = input("  시그널 보너스 적용? (0=아니오 / 1=예): ").strip()
        if raw in ("0", "1"):
            signal = int(raw)
            break
        print("  → 0 또는 1을 입력하세요.")

    return b, a, n, t, signal


def print_result(b: int, a: int, n: int, t: int, signal: int, result: dict) -> None:
    """결과를 사람이 읽기 쉬운 형식으로 출력한다."""
    print()
    print("=" * 50)
    print("  BANT 점수 계산 결과")
    print("=" * 50)
    print(f"  입력값: B={b}  A={a}  N={n}  T={t}  시그널={signal}")
    print()
    print("  [항목별 기여 점수]")
    for label, contrib in result["breakdown"].items():
        print(f"    {label:20s}: {contrib:5.1f}점")
    print()
    print(f"  가중 합산 (보너스 전): {result['weighted_raw']:5.1f}점")
    if signal:
        print(f"  시그널 보너스 (+10%): {result['bonus']:5.1f}점")
    else:
        print("  시그널 보너스:           미적용")
    print(f"  최종 점수:             {result['total']:5.1f}점  →  {result['grade']}")
    print()
    print("  [등급 기준]")
    print("    고(高): 70점 이상  →  즉시 제안 진행")
    print("    중(中): 40~69점   →  추가 조사 후 재평가")
    print("    저(低): 40점 미만  →  보류")
    print("=" * 50)
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="B2B 리드 BANT 가중 점수 계산기 (가중치: B30%·A25%·N30%·T15%)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
예시:
  python3 lead_scorer.py --b 4 --a 3 --n 5 --t 2
  python3 lead_scorer.py --b 4 --a 3 --n 5 --t 2 --signal 1
  python3 lead_scorer.py          (대화형 입력 모드)
        """,
    )
    parser.add_argument("--b", metavar="1-5", help="Budget 점수 (1~5)")
    parser.add_argument("--a", metavar="1-5", help="Authority 점수 (1~5)")
    parser.add_argument("--n", metavar="1-5", help="Need 점수 (1~5)")
    parser.add_argument("--t", metavar="1-5", help="Timeline 점수 (1~5)")
    parser.add_argument(
        "--signal",
        metavar="0|1",
        default="0",
        help="시그널 보너스 적용 여부 (0=아니오, 1=예, 기본값: 0)",
    )

    args = parser.parse_args()

    # CLI 인수가 하나도 없으면 대화형 모드
    if args.b is None and args.a is None and args.n is None and args.t is None:
        b, a, n, t, signal = interactive_input()
    else:
        # 필수 인수 누락 확인
        missing = [
            flag
            for flag, val in [("--b", args.b), ("--a", args.a), ("--n", args.n), ("--t", args.t)]
            if val is None
        ]
        if missing:
            print(
                f"오류: 다음 인수가 필요합니다: {', '.join(missing)}\n"
                "모든 인수를 생략하면 대화형 입력 모드로 실행됩니다.",
                file=sys.stderr,
            )
            parser.print_usage(sys.stderr)
            sys.exit(1)

        b = validate_score(args.b, "Budget(B)")
        a = validate_score(args.a, "Authority(A)")
        n = validate_score(args.n, "Need(N)")
        t = validate_score(args.t, "Timeline(T)")
        signal = validate_signal(args.signal)

    result = compute_score(b, a, n, t, signal)
    print_result(b, a, n, t, signal, result)


if __name__ == "__main__":
    main()
