from services.plans import PLANS, PLAN_ORDER, tenant_has_feature


def test_trial_has_all_features_regardless_of_plan():
    tenant = {"status": "trial", "plan": None}
    assert tenant_has_feature(tenant, "voice") is True
    assert tenant_has_feature(tenant, "advanced_stats") is True
    assert tenant_has_feature(tenant, "resume_autofill") is True
    assert tenant_has_feature(tenant, "interview_scheduling") is True


def test_start_plan_has_no_extra_features():
    tenant = {"status": "active", "plan": "start"}
    assert tenant_has_feature(tenant, "voice") is False
    assert tenant_has_feature(tenant, "advanced_stats") is False


def test_business_plan_features():
    tenant = {"status": "active", "plan": "business"}
    for f in ("voice", "interview_scheduling", "advanced_stats", "resume_autofill"):
        assert tenant_has_feature(tenant, f) is True


def test_no_tenant_or_no_plan_denies():
    assert tenant_has_feature(None, "voice") is False
    assert tenant_has_feature({"status": "active", "plan": None}, "voice") is False


def test_plan_prices_increase_with_tier():
    prices = [PLANS[key]["price"] for key in PLAN_ORDER]
    assert prices == sorted(prices)


def test_plan_limits_increase_with_tier():
    for key in ("applications", "vacancies", "days"):
        values = [PLANS[p][key] for p in PLAN_ORDER]
        assert values == sorted(values), f"{key} tartib bo'yicha o'smayapti"
