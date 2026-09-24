"""Definizioni alternative della coppia di jet VBF, applicate al nodo grezzo.

Tutte e tre richiedono i tagli di base della VBF (analysis/AnalysisTools.h,
struct VBFJets): m(jj) >= 400 GeV, |Delta eta(jj)| >= 2.5, pT >= 35/25 GeV.

  maxmjj   fra le coppie di jet preselezionati che passano i tagli, quella con
           m(jj) massima.  E' FindVBFJets, cioe' la produzione: nessuna
           ridefinizione, restano le colonne dello skim.
  hardest  fra tutte le coppie di jet preselezionati che passano i tagli, la
           piu' dura in pT dei singoli jet: prima il leading piu' duro, a parita'
           il subleading piu' duro (ordine lessicografico nella collezione
           SelectedJet, ordinata in pT).
  leading  i due jet di pT piu' alto fra tutti i jet ricostruiti (pT > 25 GeV,
           separati dai muoni): la coppia esiste solo se tutti e due passano la
           preselezione (ID, |eta|, veto map, horn) e i tagli.  Un jet leading
           che cade nell'horn toglie l'evento dalla VBF invece di essere
           sostituito dal successivo: e' l'unica differenza con hardest.

Si sovrascrivono solo HasVBF e VBFJetIdx_1/2: m_jj, vbfjet*_*, le variabili
del DNN e le componenti Hard/PU del DY si ricalcolano da li' (common/add_vars.py,
common/jet_component_splitting.py).  Solo per la variazione nominale dei jet.
"""

from __future__ import annotations

import ROOT

DEFINITIONS = ("maxmjj", "hardest", "leading")

_DECLARED = False

_CODE = r"""
namespace vbfdef {

using RVecF = ROOT::VecOps::RVec<float>;
using RVecI = ROOT::VecOps::RVec<int>;
using RVecB = ROOT::VecOps::RVec<bool>;
using P4 = ROOT::Math::LorentzVector<ROOT::Math::PtEtaPhiM4D<double>>;

constexpr float kMjj = 400.f, kDeta = 2.5f, kPt1 = 35.f, kPt2 = 25.f, kJetPtMin = 25.f;

// La coppia (i, j) di SelectedJet passa i tagli di base? i e' il jet piu' duro.
inline bool PassesCuts(const RVecF& pt, const RVecF& eta, const RVecF& phi,
                       const RVecF& mass, int i, int j) {
    const P4 a(pt[i], eta[i], phi[i], mass[i]), b(pt[j], eta[j], phi[j], mass[j]);
    return (a + b).M() >= kMjj && std::abs(eta[i] - eta[j]) >= kDeta
        && pt[i] >= kPt1 && pt[j] >= kPt2;
}

// Indici {leg1, leg2} nella collezione SelectedJet, ordinata in pT; {-1,-1} se niente.
RVecI Hardest(const RVecF& pt, const RVecF& eta, const RVecF& phi, const RVecF& mass) {
    // SelectedJet e' ordinata in pT: la prima coppia (i, j) che passa e' la piu' dura.
    RVecI out{-1, -1};
    for (int i = 0; i < (int)pt.size(); ++i)
        for (int j = i + 1; j < (int)pt.size(); ++j)
            if (PassesCuts(pt, eta, phi, mass, i, j)) { out[0] = i; out[1] = j; return out; }
    return out;
}

RVecI Leading(const RVecF& jet_pt, const RVecF& jet_eta, const RVecF& jet_phi,
              const RVecB& jet_good, const RVecI& selected_idx,
              float mu1_eta, float mu1_phi, float mu2_eta, float mu2_phi,
              const RVecF& pt, const RVecF& eta, const RVecF& phi, const RVecF& mass) {
    RVecI out{-1, -1};
    int lead[2] = {-1, -1};
    for (int k = 0; k < (int)jet_pt.size(); ++k) {
        if (jet_pt[k] <= kJetPtMin) continue;
        if (ROOT::VecOps::DeltaR(jet_eta[k], mu1_eta, jet_phi[k], mu1_phi) <= 0.4f) continue;
        if (ROOT::VecOps::DeltaR(jet_eta[k], mu2_eta, jet_phi[k], mu2_phi) <= 0.4f) continue;
        if (lead[0] < 0 || jet_pt[k] > jet_pt[lead[0]]) { lead[1] = lead[0]; lead[0] = k; }
        else if (lead[1] < 0 || jet_pt[k] > jet_pt[lead[1]]) lead[1] = k;
    }
    if (lead[1] < 0 || !jet_good[lead[0]] || !jet_good[lead[1]]) return out;
    int sel[2] = {-1, -1};
    for (int s = 0; s < (int)selected_idx.size(); ++s)
        for (int l = 0; l < 2; ++l)
            if (selected_idx[s] == lead[l]) sel[l] = s;
    if (sel[0] < 0 || sel[1] < 0) return out;
    if (sel[0] > sel[1]) std::swap(sel[0], sel[1]);
    if (!PassesCuts(pt, eta, phi, mass, sel[0], sel[1])) return out;
    out[0] = sel[0]; out[1] = sel[1];
    return out;
}

}
"""

_EXPRESSION = {
    "hardest": "vbfdef::Hardest(SelectedJet_pt, SelectedJet_eta, SelectedJet_phi, SelectedJet_mass)",
    "leading": ("vbfdef::Leading(Jet_pt, Jet_eta, Jet_phi, Jet_NoOverlapWithMuons, SelectedJet_idx, "
                "mu1_eta, mu1_phi, mu2_eta, mu2_phi, "
                "SelectedJet_pt, SelectedJet_eta, SelectedJet_phi, SelectedJet_mass)"),
}


def apply_vbf_pair_definition(rdf, definition):
    """Ridefinisce HasVBF e VBFJetIdx_1/2 sul nodo grezzo dello skim."""
    global _DECLARED
    if definition in (None, "", "maxmjj"):
        return rdf
    if definition not in _EXPRESSION:
        raise ValueError(f"Unknown VBF pair definition {definition!r}; available {DEFINITIONS}")
    if not _DECLARED:
        ROOT.gInterpreter.Declare(_CODE)
        _DECLARED = True
    rdf = rdf.Define("VBFPairIdx__def", _EXPRESSION[definition])
    rdf = rdf.Redefine("VBFJetIdx_1", "VBFPairIdx__def[0]")
    rdf = rdf.Redefine("VBFJetIdx_2", "VBFPairIdx__def[1]")
    return rdf.Redefine("HasVBF", "VBFPairIdx__def[0] >= 0")
