"""Compatibility patches for incomplete Flashsim NanoAOD schemas."""
import ROOT


ROOT.gInterpreter.Declare(
    """
    namespace flashsim_patch {
    using RVecF = ROOT::VecOps::RVec<float>;
    using RVecI = ROOT::VecOps::RVec<int>;
    // Reconstruct the closest-lepton association of CMSSW LeptonFSRProducer
    // from the stored NanoAOD kinematics. Isolation and footprint selection
    // are assumed to have been applied when producing the FSR collection.
    RVecI fsr_electron_indices(const RVecF& fsr_pt,
                              const RVecF& fsr_eta, const RVecF& fsr_phi,
                              const RVecF& mu_pt, const RVecF& mu_eta, const RVecF& mu_phi,
                              const RVecF& el_pt, const RVecF& el_eta, const RVecF& el_phi) {
        RVecI indices(fsr_pt.size(), -1);
        for (size_t i = 0; i < fsr_pt.size(); ++i) {
            double best_dr = 0.5;
            const double max_dr_et = 0.05 * double(fsr_pt[i]) * fsr_pt[i];
            for (size_t j = 0; j < mu_pt.size(); ++j) {
                if (mu_pt[j] < 3. || std::abs(mu_eta[j]) > 2.4) continue;
                const double dr = ROOT::VecOps::DeltaR(double(mu_eta[j]), double(fsr_eta[i]),
                                                       double(mu_phi[j]), double(fsr_phi[i]));
                if (dr > 0.0001 && dr < best_dr && dr < max_dr_et) best_dr = dr;
            }
            for (size_t j = 0; j < el_pt.size(); ++j) {
                if (el_pt[j] < 5. || std::abs(el_eta[j]) > 2.5) continue;
                const double dr = ROOT::VecOps::DeltaR(double(el_eta[j]), double(fsr_eta[i]),
                                                       double(el_phi[j]), double(fsr_phi[i]));
                if (dr > 0.0001 && dr < best_dr && dr < max_dr_et) {
                    best_dr = dr;
                    indices[i] = j;
                }
            }
        }
        return indices;
    }

    }
    """
)


def is_flashsim_sample(dataset_name, is_data=False):
    return not is_data and "flashsim" in dataset_name.lower()


# Add optional Muon_* observables here. Listed columns are omitted only when
# absent in Flashsim; existing branches and non-Flashsim samples are preserved.
FLASHSIM_OPTIONAL_MUON_COLUMNS = (
    "Muon_pdgId",
    "Muon_svIdx",
    "Muon_genPartFlav",
    "Electron_mvaIso_WP90"
)

def patch_flashsim_redefine_cols(df,dataset_name,is_data=False):
    if not is_flashsim_sample(dataset_name, is_data):
        return df
    if "Electron_mvaIso_WP90" in df.GetColumnNames():
        return df
    df = df.Define("Electron_mvaIso_WP90", "Electron_mvaIso")
    return df
def patch_flashsim_muon_columns(df, columns, dataset_name, is_data=False):
    """Omit explicitly optional, missing Flashsim muon observables."""
    if not is_flashsim_sample(dataset_name, is_data):
        return columns
    missing = {
        column for column in columns
        if column in FLASHSIM_OPTIONAL_MUON_COLUMNS and not df.HasColumn(column)
    }
    for col in missing:
        if col in df.GetColumnNames():
            missing.remove(col)
    if missing:
        print("[PATCH Flashsim] Omitting missing muon columns: " + ", ".join(sorted(missing)))
    return [column for column in columns if column not in missing]


def apply_flashsim_patch(df, dataset_name, is_data=False):
    if not is_flashsim_sample(dataset_name, is_data):
        return df
    if not df.HasColumn("FsrPhoton_electronIdx"):
        print("[PATCH Flashsim] Reconstructing missing FsrPhoton_electronIdx")
        df = df.Define(
            "FsrPhoton_electronIdx",
            "flashsim_patch::fsr_electron_indices(FsrPhoton_pt, FsrPhoton_eta, FsrPhoton_phi, "
            "Muon_pt, Muon_eta, Muon_phi, Electron_pt, Electron_eta, Electron_phi)",
        )
    return df
