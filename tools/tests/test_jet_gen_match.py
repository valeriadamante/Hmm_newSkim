"""Execute the production C++ matching method with missing NanoAOD matches."""
from pathlib import Path
import pytest


def test_gen_match_missing_index_and_geometric_fallback():
    ROOT = pytest.importorskip('ROOT')
    header = (Path(__file__).resolve().parents[2] / 'corrections/jets.h').read_text()
    method = header[header.index('std::size_t findGenMatch('):header.index('std::map<std::pair<UncSource, UncScale>, RVecLV> getShiftedP4(')]
    ROOT.gInterpreter.Declare('#include <ROOT/RVec.hxx>\n#include <Math/VectorUtil.h>\n#include <limits>\nstruct HornGenMatchTest {\n' + method + '\n};')
    matcher = ROOT.HornGenMatchTest()
    vec = ROOT.VecOps.RVec('float')
    pts, etas, phis = vec([50.]), vec([2.7]), vec([0.])
    assert matcher.findGenMatch(50., 2.7, 0., 1, pts, etas, phis, 5.) == 0
    assert matcher.findGenMatch(50., 2.7, 0., 999, pts, etas, phis, 5.) == 0
    assert matcher.findGenMatch(50., 2.7, 1., 1, pts, etas, phis, 5.) == 1
    assert matcher.findGenMatch(100., 2.7, 0., 1, pts, etas, phis, 5.) == 1
    assert matcher.findGenMatch(50., 2.7, 0., 0, vec(), vec(), vec(), 5.) == 0
    assert matcher.findGenMatch(50., 2.7, 0., 0, pts, vec(), vec(), 5.) == 1


def test_cpp_horn_jer_and_residual_policy():
    ROOT = pytest.importorskip('ROOT')
    header = (Path(__file__).resolve().parents[2] / 'corrections/jets.h').read_text()
    floor = header.split('const bool applyResidualPtFloor =', 1)[1].split(';', 1)[0]
    horn = header[header.index('const bool is_jet_in_horn ='):header.index('corrected_pt *= jersmear_factor;')]
    ROOT.gInterpreter.Declare('''
    bool hornResidualTest(std::string year_, float abs_eta, bool apply_horn_mitigation) {
        return ''' + floor + ''';
    }
    float hornSmearTest(std::string year_, float abs_eta, bool apply_horn_mitigation, float genjet_pt) {
        float jersmear_factor = 1.2f;
        ''' + horn + '''
        return jersmear_factor;
    }
    ''')
    for year in ('2022', '2022EE', '2023', '2023BPix', '2024', '2025', '2026'):
        for enabled in (False, True):
            for eta in (1.9, 2.0, 2.1, 2.49, 2.5, 2.6, 2.99, 3., 3.1):
                mitigation = year not in ('2025', '2026') or enabled
                residual = (year == '2024' or year in ('2025', '2026') and enabled) and 2. < eta < 2.5
                assert ROOT.hornResidualTest(year, eta, enabled) == residual
                for genpt in (-1., 50.):
                    expected = 1. if mitigation and 2.5 < eta < 3. and genpt < 0 else 1.2
                    assert ROOT.hornSmearTest(year, eta, enabled, genpt) == pytest.approx(expected)


def test_residual_floor_uses_pt_after_mc_jec_and_only_for_data():
    ROOT = pytest.importorskip('ROOT')
    header = (Path(__file__).resolve().parents[2] / 'corrections/jets.h').read_text()
    method = header[header.index('float evaluateJECSeparately('):header.index('std::size_t findGenMatch(')]
    ROOT.gInterpreter.Declare('''
    struct HornResidualEvaluationTest {
        int corr_l1_ = 1, corr_l2_ = 2, corr_l2l3res_ = 3;
        mutable float residual_pt = -1;
        template<typename... Args> float safeEvaluate(int correction, Args... args) const {
            if (correction == 1) return 2.f;
            if (correction == 2) return 1.5f;
            float values[] = {float(args)...};
            residual_pt = values[sizeof...(args)-1];
            return 1.f;
        }
        ''' + method + '''
    };
    ''')
    for run_dependent in (False, True):
        for floor in (False, True):
            for raw_pt in (8., 10., 12.):
                for data in (False, True):
                    provider = ROOT.HornResidualEvaluationTest()
                    assert provider.evaluateJECSeparately(raw_pt, 2.2, 0., .5, 20., 1, run_dependent, False, data, floor) == pytest.approx(3.)
                    expected = max(30., raw_pt * 3) if floor else raw_pt * 3
                    assert provider.residual_pt == pytest.approx(expected if data else -1.)
