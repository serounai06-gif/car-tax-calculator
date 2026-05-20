from flask import Flask, render_template, request, jsonify
from datetime import date

app = Flask(__name__)

# ───── 세율표 (원/cc) : (cc 상한, 세율) — 상한 None 은 초과 구간 ─────
RATES = {
    ('non-business', 'passenger'): [(1000, 80), (1600, 140), (2000, 200), (None, 220)],
    ('business',     'passenger'): [(1000, 18), (1600, 18),  (2000, 19),  (2500, 19),  (None, 24)],
}

JANUARY_DISCOUNT_RATE = 0.05   # 연납공제율 (2024년부터 5%)
EDUCATION_TAX_RATE    = 0.30   # 지방교육세율


def lookup_rate(usage, vehicle_type, cc):
    table = RATES.get((usage, vehicle_type))
    if table is None:
        return None
    for limit, rate in table:
        if limit is None or cc <= limit:
            return rate
    return table[-1][1]


def vehicle_age(base_date, ref_date):
    """ref_date 기준 만 차령(년)."""
    years = ref_date.year - base_date.year
    if (ref_date.month, ref_date.day) < (base_date.month, base_date.day):
        years -= 1
    return max(years, 0)


def age_reduction_rate(age):
    """차령에 따른 경감율 반환 (0.0 ~ 0.50)."""
    if age < 3:
        return 0.0
    return min((age - 2) * 0.05, 0.50)


def calc_half(cc, rate, reduction):
    """상반기 또는 하반기 단계별 세액 계산."""
    step1    = round(cc * rate / 2)                       # 과세표준 × 세율
    step2    = round(step1 * (1 - reduction))             # × 차령경감율
    discount = round(step2 * JANUARY_DISCOUNT_RATE)
    step3    = step2 - discount                           # × 연납할인율
    edu      = round(step3 * EDUCATION_TAX_RATE)
    return dict(
        step1=step1,
        step2=step2,
        discount=discount,
        step3=step3,
        edu=edu,
        total=step3 + edu,
        reduction_pct=round(reduction * 100),
    )


@app.route('/')
def index():
    return render_template('index.html', today=date.today().isoformat())


@app.route('/calculate', methods=['POST'])
def calculate():
    body = request.get_json(silent=True) or {}
    usage        = body.get('usage', '').strip()
    vehicle_type = body.get('vehicle_type', '').strip()
    base_date_s  = body.get('base_date', '').strip()
    cc_raw       = body.get('cc')

    if not all([usage, vehicle_type, base_date_s, cc_raw is not None]):
        return jsonify(error='모든 항목을 입력해주세요.'), 400

    try:
        cc        = int(cc_raw)
        base_date = date.fromisoformat(base_date_s)
    except (ValueError, TypeError):
        return jsonify(error='입력값이 올바르지 않습니다.'), 400

    if cc <= 0 or cc > 10000:
        return jsonify(error='과세표준은 1~10,000cc 범위여야 합니다.'), 400
    if base_date > date.today():
        return jsonify(error='차령기산일이 미래 날짜입니다.'), 400

    rate = lookup_rate(usage, vehicle_type, cc)
    if rate is None:
        return jsonify(error='해당 용도/차종의 세율은 아직 지원되지 않습니다.'), 400

    today  = date.today()
    h1_ref = date(today.year, 1, 1)   # 상반기 기준일
    h2_ref = date(today.year, 7, 1)   # 하반기 기준일

    age_h1 = vehicle_age(base_date, h1_ref)
    age_h2 = vehicle_age(base_date, h2_ref)

    h1 = calc_half(cc, rate, age_reduction_rate(age_h1))
    h2 = calc_half(cc, rate, age_reduction_rate(age_h2))

    grand_total = h1['total'] + h2['total']

    result = dict(
        rate_per_cc=rate,
        age_h1=age_h1,
        age_h2=age_h2,
        discount_pct=round(JANUARY_DISCOUNT_RATE * 100),
        h1=h1,
        h2=h2,
        grand_total=grand_total,
        refund=None,
    )

    # 소유권이전 환급 일할계산 (선택)
    transfer_date_s = (body.get('transfer_date') or '').strip()
    if transfer_date_s:
        try:
            transfer_date = date.fromisoformat(transfer_date_s)
        except ValueError:
            return jsonify(error='소유권이전일자가 올바르지 않습니다.'), 400

        year       = today.year
        year_start = date(year, 1, 1)
        year_end   = date(year, 12, 31)
        total_days = (year_end - year_start).days + 1        # 365 or 366
        refund_days = max((year_end - transfer_date).days, 0) # 이전일 다음날 ~ 12월 31일

        result['refund'] = dict(
            transfer_date=transfer_date_s,
            refund_days=refund_days,
            total_days=total_days,
            refund_amount=round(grand_total * refund_days / total_days),
        )

    return jsonify(result)


if __name__ == '__main__':
    app.run(debug=True)
