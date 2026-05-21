from flask import Flask, render_template, request, jsonify
from datetime import date

app = Flask(__name__)

# ── 승용차: CC당 세율 (cc 상한, 원/cc), 상한 None = 초과구간 ──
CC_RATES = {
    ('non-business', 'passenger'): [(1000, 80), (1600, 140), (None, 200)],
    ('business',     'passenger'): [(1000, 18), (1600, 18), (2000, 19), (2500, 19), (None, 24)],
}

# ── 고정 연세액 (지방세법 §127, 원/년) ──
FIXED_RATES = {
    # 승합
    ('non-business', 'van'): {
        'large_general': 115000,   # 대형일반버스
        'small_general':  65000,   # 소형일반버스
    },
    ('business', 'van'): {
        'express':       100000,   # 고속버스
        'large_charter':  70000,   # 대형전세버스
        'small_charter':  50000,   # 소형전세버스
        'large_general':  42000,   # 대형일반버스
        'small_general':  25000,   # 소형일반버스
    },
    # 화물 (비영업용/영업용 세율 상이)
    ('non-business', 'cargo'): {
        't1':   28500,   # 1,000kg 이하
        't2':   34500,   # 2,000kg 이하
        't3':   48000,   # 3,000kg 이하
        't4':   63000,   # 4,000kg 이하
        't5':   79500,   # 5,000kg 이하
        't8':  130500,   # 8,000kg 이하
        't10': 157500,   # 10,000kg 이하
    },
    ('business', 'cargo'): {
        't1':   6600,
        't2':   9600,
        't3':  13500,
        't4':  18000,
        't5':  22500,
        't8':  36000,
        't10': 45000,
    },
    # 특수
    ('non-business', 'special'): {
        'large': 157500,   # 대형특수자동차
        'small':  58500,   # 소형특수자동차
    },
    ('business', 'special'): {
        'large': 36000,
        'small': 13500,
    },
    # 이륜 (3톤 이하 소형자동차)
    ('non-business', 'motorcycle'): {'default': 18000},
    ('business',     'motorcycle'): {'default':  3300},
    # 건설기계 (추후 확인 필요)
    ('non-business', 'construction'): {'large': 36000, 'small': 18000},
    ('business',     'construction'): {'large': 36000, 'small': 18000},
}

JANUARY_DISCOUNT_RATE = 0.05
EDUCATION_TAX_RATE    = 0.30


def lookup_cc_rate(usage, cc):
    table = CC_RATES.get((usage, 'passenger'), [])
    for limit, rate in table:
        if limit is None or cc <= limit:
            return rate
    return None


def vehicle_age(base_date, tax_year, half):
    """
    지방세법 시행령 §122② 기준 차령 계산:
    - 기산일 1~6월: 두 기분 모두 과세연도 - 등록연도 + 1
    - 기산일 7~12월: 1기분 = 과세연도 - 등록연도, 2기분 = +1
    """
    if 1 <= base_date.month <= 6:
        n = tax_year - base_date.year + 1
    else:
        n = tax_year - base_date.year + (1 if half == 2 else 0)
    return max(n, 0)


def age_reduction_rate(age):
    if age < 3:
        return 0.0
    return min((age - 2) * 0.05, 0.50)


def calc_half(annual_tax, reduction):
    """연납공제는 합산 후 총액에서 별도 차감 — 여기서는 차령경감까지만 계산."""
    step1 = round(annual_tax / 2)
    step2 = round(step1 * (1 - reduction))
    edu   = round(step2 * EDUCATION_TAX_RATE)
    return dict(
        step1=step1,
        step2=step2,
        edu=edu,
        total=step2 + edu,
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
    sub_type     = body.get('sub_type', '').strip()
    cc_raw       = body.get('cc')

    if not all([usage, vehicle_type, base_date_s]):
        return jsonify(error='모든 항목을 입력해주세요.'), 400

    try:
        base_date = date.fromisoformat(base_date_s)
    except (ValueError, TypeError):
        return jsonify(error='차령기산일이 올바르지 않습니다.'), 400

    if base_date > date.today():
        return jsonify(error='차령기산일이 미래 날짜입니다.'), 400

    if vehicle_type == 'passenger':
        if cc_raw is None:
            return jsonify(error='배기량(cc)을 입력해주세요.'), 400
        try:
            cc = int(cc_raw)
        except (ValueError, TypeError):
            return jsonify(error='배기량이 올바르지 않습니다.'), 400
        if cc <= 0 or cc > 10000:
            return jsonify(error='배기량은 1~10,000cc 범위여야 합니다.'), 400

        rate = lookup_cc_rate(usage, cc)
        if rate is None:
            return jsonify(error='세율을 찾을 수 없습니다.'), 400

        annual_tax   = cc * rate
        rate_display = f'{rate:,}원/cc'
        base_display = f'{cc:,}cc'
    else:
        if not sub_type:
            return jsonify(error='세부종류를 선택해주세요.'), 400

        annual_tax = (FIXED_RATES.get((usage, vehicle_type)) or {}).get(sub_type)
        if annual_tax is None:
            return jsonify(error='해당 차종/세부종류의 세율이 없습니다.'), 400

        rate_display = f'연 {annual_tax:,}원'
        base_display = '연세액'

    today    = date.today()
    tax_year = today.year

    age_h1 = vehicle_age(base_date, tax_year, half=1)
    age_h2 = vehicle_age(base_date, tax_year, half=2)

    h1 = calc_half(annual_tax, age_reduction_rate(age_h1))
    h2 = calc_half(annual_tax, age_reduction_rate(age_h2))

    subtotal     = h1['total'] + h2['total']
    # 연납공제: 2월~12월(11개월)분에만 5% 적용 — 1월분은 당월이라 공제 제외
    discount_amt = round(subtotal * 11 / 12 * JANUARY_DISCOUNT_RATE)
    grand_total  = subtotal - discount_amt

    result = dict(
        rate_display=rate_display,
        base_display=base_display,
        annual_tax=annual_tax,
        age_h1=age_h1,
        age_h2=age_h2,
        discount_pct=round(JANUARY_DISCOUNT_RATE * 100),
        discount_amt=discount_amt,
        subtotal=subtotal,
        h1=h1,
        h2=h2,
        grand_total=grand_total,
        refund=None,
    )

    transfer_date_s = (body.get('transfer_date') or '').strip()
    if transfer_date_s:
        try:
            transfer_date = date.fromisoformat(transfer_date_s)
        except ValueError:
            return jsonify(error='소유권이전일자가 올바르지 않습니다.'), 400

        year        = today.year
        year_start  = date(year, 1, 1)
        year_end    = date(year, 12, 31)
        total_days  = (year_end - year_start).days + 1
        refund_days = max((year_end - transfer_date).days, 0)

        result['refund'] = dict(
            transfer_date=transfer_date_s,
            refund_days=refund_days,
            total_days=total_days,
            refund_amount=round(grand_total * refund_days / total_days),
        )

    return jsonify(result)


if __name__ == '__main__':
    app.run(debug=True)
