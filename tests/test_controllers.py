from vncrcc.controller_activity import is_ncr_controller


def ctl(fac, artcc="ZDC", observer=False):
    return {"artccId": artcc, "primaryFacilityId": fac, "isObserver": observer}


def test_ncr_facilities_included():
    for fac in ("PCT", "DCA", "IAD", "BWI", "ADW", "ZDC"):
        assert is_ncr_controller(ctl(fac)), fac


def test_rest_of_zdc_excluded():
    for fac in ("RIC", "ORF", "ROA", "CHO"):
        assert not is_ncr_controller(ctl(fac)), fac


def test_other_artcc_and_observers_excluded():
    assert not is_ncr_controller(ctl("ATL", artcc="ZTL"))
    assert not is_ncr_controller(ctl("PCT", observer=True))
