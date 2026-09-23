import os, re, sys
import ROOT
import math
import yaml
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.systematic_correlations import nuisance_name as correlated_nuisance_name

absolutepath = True

def parse_uncertainty_value(value):
    # Plain numeric value from YAML (int/float)

    if not isinstance(value, str):
        v = float(value)
        return v, v

    s = value.strip()

    # Division -> evaluate and treat symmetrically
    if "/" in s:
        expr = s.replace("%", "")
        val = safe_eval_number(expr)
        val = abs(val)
        return val, val

    symmetric = False
    tmp = s
    if "±" in tmp or "+/-" in tmp or "+-" in tmp:
        symmetric = True
        tmp = tmp.replace("±", " ").replace("+/-", " ").replace("+-", " ")

    # Find all numbers (allow scientific notation, optional leading sign)
    num_pattern = re.compile(r'[+-]?\s*\d*\.?\d+(?:[eE][+-]?\d+)?')
    matches = num_pattern.findall(tmp)
    nums = [float(m.replace(" ", "")) for m in matches]

    if not nums:
        raise ValueError(f"Could not parse uncertainty value: {value!r}")

    if symmetric or (len(nums) == 1):
        val = abs(nums[0])
        return val, val

    up = abs(nums[0])
    down = abs(nums[1])

    return up, down


def safe_eval_number(expr):
    """Safely evaluate a simple arithmetic expression -> float."""
    import ast
    import operator
    ops = {
        ast.Add: operator.add, ast.Sub: operator.sub,
        ast.Mult: operator.mul, ast.Div: operator.truediv,
        ast.USub: operator.neg, ast.UAdd: operator.pos,
    }

    def _eval(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.BinOp):
            return ops[type(node.op)](_eval(node.left), _eval(node.right))
        if isinstance(node, ast.UnaryOp):
            return ops[type(node.op)](_eval(node.operand))
        raise ValueError(f"Unsupported expression: {expr!r}")

    return float(_eval(ast.parse(expr, mode="eval").body))


def build_xsec_dictionary(yaml_path, processes):
    with open(yaml_path, "r") as f:
        cfg = yaml.safe_load(f)
    result = {}
    for process in processes:
        entry = cfg.get(process)
        if not entry:
            print(process, "missing xsec uncertainty")
            continue

        unc = entry.get("unc", {}) or {}

        chosen = None
        if "total" in unc:
            chosen = unc["total"]
        elif "theory" in unc:
            chosen = unc["theory"]

        if chosen is None:
          print(process,"has no theory uncertainty")
          continue
        else:
            raw = chosen.get("value")
            up_frac, down_frac = parse_uncertainty_value(raw)

            # Determine whether the value is a percentage
            is_percent = bool(chosen.get("isPercentage", False))
            if isinstance(raw, str) and "%" in raw:
                is_percent = True

            if is_percent:
                # percentage -> fraction relative to 1
                up_frac /= 100.0
                down_frac /= 100.0
            else:
                # absolute uncertainty -> divide by cross section
                xsec = _get_crosssec(entry)
                if xsec is None or xsec == 0:
                    print(process, "cannot normalize absolute uncertainty (no crossSec)")
                else:
                    up_frac /= abs(xsec)
                    down_frac /= abs(xsec)

        # Store the Combine kappa factors: down = 1 - down_frac, up = 1 + up_frac
        result[process] = {
            "up": 1.0 + up_frac,
            "down": 1.0 - down_frac,
        }

    return result


def _get_crosssec(entry):
    """Return the numeric cross section, evaluating expressions if needed."""
    raw = entry.get("crossSec")
    if raw is None:
        return None
    if not isinstance(raw, str):
        return float(raw)
    expr = raw.split("#")[0].strip()
    try:
        return safe_eval_number(expr)
    except Exception:
        return None



def check_process_histograms(filepath, channel, proc, uncertainties):
    fname = os.path.join(filepath, proc + ".root")
    if not os.path.isfile(fname):
        print("  WARNING: file not found for process {}: {} -> turning off".format(proc, fname))
        return False

    tf = ROOT.TFile.Open(fname)
    if not tf or tf.IsZombie():
        print("  WARNING: could not open file for process {}: {} -> turning off".format(proc, fname))
        return False

    good = True

    # nominal histogram
    nominal_name = channel + "/DNN_NNOutput"
    h = tf.Get(nominal_name)
    if not h:
        print("  WARNING: nominal histogram '{}' missing for process {} -> turning off".format(nominal_name, proc))
        good = False
    else:
        integral = h.Integral()
        if integral <= 0:
            print("  {}: nominal integral negative ({:.6g}) -> turning off".format(proc, integral))
            good = False

    # systematic histograms: for each uncertainty that applies to this process,
    # check both Up and Down variations
    if good:
        for unc in uncertainties:
            uncname = unc[0]
            unctype = unc[1]
            proc_tag = unc[3]

            # only shape uncertainties have histograms
            if unctype != "shape":
                continue
            # skip uncertainties that don't apply to this process
            if proc_tag is not None and proc not in proc_tag:
                continue

            for direction in ["Up", "Down"]:
                hist_name = "{ch}/DNN_NNOutput_{unc}{dir}".format(
                    ch=channel, unc=uncname, dir=direction
                )
                hs = tf.Get(hist_name)
                if not hs:
                    print("  {}: systematic '{}{}' missing -> turning off".format(
                        proc, uncname, direction))
                    good = False
                    break
                integral = hs.Integral()
                if integral <= 0:
                    print("  {}: systematic '{}{}' integral negative ({:.6g}) -> turning off".format(
                        proc, uncname, direction, integral))
                    good = False
                    break
            if not good:
                break

    tf.Close()
    return good

def build_uncertainties(yaml_path, processes, year):
    #Build the uncertainties list from the configuration file.
    with open(yaml_path, "r") as f:
        cfg = yaml.safe_load(f)

    uncertainties = []

    # Combine systematics and weights sections
    sections = {}
    sections.update(cfg["systematics"])
    sections.update(cfg["weights"])

    expanded = {}
    for key, block in sections.items():
        if block.get('components'):
            for component in block['components']:
                expanded[component] = dict(block, name=f'{component}{{era}}')
        else:
            expanded[key] = block
    for key, block in expanded.items():
        name = block.get("name", "")
        if name=="":
          continue
        name = name.replace("_{scale}","").replace("_{}","")
        name = correlated_nuisance_name(dict(block, name=name), year,
                                         process="{process}", pdf_process="{pdf_process}")
        if name.find("{process}")!=-1:
          if name.find("QCDscale")!=-1:
            for variation in cfg["qcd_scale"]["variations"]:
              for proc in processes:
                procname = correlated_nuisance_name(dict(cfg["qcd_scale"], **variation), year,
                                                  process=cfg["qcd_scale"]["process_labels"][proc])
                key = [uncertainty[0]==procname for uncertainty in uncertainties]
                if any(key):
                  uncertainties[key.index(True)][3].append(proc)
                else:
                  uncertainties.append([procname, "shape", "1", [proc]])
          # expand into one uncertainty per process
          else:
            for proc in processes:
              procname = name.replace("{process}", proc)
              # 4th element = the process this uncertainty applies to
              uncertainties.append([procname, "shape", "1", [proc]])
        elif name.find("{pdf_process}")!=-1:
          for proc in processes:
            procname = name.replace("{pdf_process}", cfg["pdf"]["process_labels"][proc])
            key = [uncertainty[0]==procname for uncertainty in uncertainties]
            if any(key):
              uncertainties[key.index(True)][3].append(proc)
            else:
              uncertainties.append([procname, "shape", "1", [proc]])
        else:
          uncertainties.append([name, "shape", "1", None])

    for block in cfg.get("derived_systematics", {}).values():
      name = correlated_nuisance_name(block, year)
      uncertainties.append([
          name,
          "shape",
          "1",
          [block["nominal_process"]],
      ])


    return uncertainties


BASE_PATH = os.path.dirname(os.path.abspath(__file__))
ANALYSIS_PATH = os.environ.get(
    "ANALYSIS_PATH",
    os.path.abspath(os.path.join(BASE_PATH, "..")),
)

if "ANALYSIS_PATH" not in os.environ:
    print(
        f"Environment variable ANALYSIS_PATH is not set, "
        f"using {ANALYSIS_PATH} as default"
    )
else:
    print(f"Using ANALYSIS_PATH={ANALYSIS_PATH}")
CONFIG_PATH = os.path.join(ANALYSIS_PATH, "config")


#define the input names
signalprocesses = ["VBFHto2Mu_M125_powheg", "GluGluHto2Mu"]
backgroundprocesses = ["DYto2Mu_MLL105To160_2J_Hard","DYto2Mu_MLL105To160_2J_PU1","DYto2Mu_MLL105To160_2J_PU2", "EWK_2Mu2J_MLL_105to160_herwig", "ST", "VV", "TT", "TTX", "VVV", "W", "TW", "SingleH"]#"DYto2Mu_MLL105To160",
process_files = {}

lumidict = {"lumi_2022_2023_2024": {"2022": "1.0138", "2023": "1.0017", "2024": "1.0020", "2025": "-"},
            "lumi_2023_2024": {"2022": "-", "2023": "1.0127", "2024": "1.0068", "2025": "-"},
            "lumi_2024": {"2022": "-", "2023": "-", "2024": "1.0144", "2025": "-"},
            "lumi_2025": {"2022": "-", "2023": "-", "2024": "-", "2025": "1.05"}
}


def main():
    year = sys.argv[1]

    outputpath = "combine/"
    histogramfilepath = "/eos/user/v/vdamante/H_mumu/Aug25/DNN_SignalFit_VBF/WithDY012JWeights/Hists_AllSystematics_hadded/Run3_"+year+"/"

    if absolutepath:
      absolutepathname = '/'.join(histogramfilepath.split("/")[:-2])+"/"
    else:
      absolutepathname = ''

    if os.path.isdir(outputpath):
      pass
      #print("already exists")
    else:
      os.system("mkdir "+outputpath) #make directory, if it doesn't exist

    bands = ["Signal_Fit_VBF"]

    DYdict = {"2022":{"name":"DYVBFZ_fit_2J{split}_2022_2022EE","split":{"Hard":"1.013021","PU1":"1.022131","PU2":"1.058263"}},
              "2023":{"name":"DYVBFZ_fit_2J{split}_2023_2023BPix","split":{"Hard":"1.023091","PU1":"1.040727","PU2":"1.039661"}},
              "2024":{"name":"DYVBFZ_fit_2J{split}_2024","split":{"Hard":"1.003436","PU1":"1.009221","PU2":"1.008642"}},
              "2025":{"name":"DYVBFZ_fit_2J{split}_2025","split":{"Hard":"1.003906","PU1":"1.009983","PU2":"1.009053"}}}
    xsecdict = build_xsec_dictionary(CONFIG_PATH+"/crossSections13p6TeV.yaml",signalprocesses+backgroundprocesses)

    for band in bands:
      filename = band + "_" + year
      bandname = band# + "_" + year
      print(bandname," ",filename)

      uncertainties = build_uncertainties(CONFIG_PATH+"/Run3_"+year+"/systematics.yaml",signalprocesses+backgroundprocesses, year)
      for key in lumidict.keys():
        uncertainties.append([key, "lnN", lumidict[key][year.replace("EE","").replace("BPix","")], None])
      for key in xsecdict.keys():
        uncertainties.append([key, "lnN", str(round(xsecdict[key]['down'],4))+'/'+str(round(xsecdict[key]['up'],4)), None])

      good_processes = {}
      for proc in signalprocesses + backgroundprocesses:
          is_good = check_process_histograms(histogramfilepath, band, proc, uncertainties)
          good_processes[proc] = is_good
          if not is_good:
              print("  -> Process '{}' will be turned OFF".format(proc))

      for key in DYdict[year.replace("EE","").replace("BPix","")]["split"].keys():
        uncertainties.append([DYdict[year.replace("EE","").replace("BPix","")]["name"].replace("{split}",key), "lnN", DYdict[year.replace("EE","").replace("BPix","")]["split"][key], "DYto2Mu_MLL105To160_2J_"+key])
      # # Build the filtered lists of processes to actually write in the datacard
      # signalprocesses = [p for p in signalprocesses if good_processes[p]]
      # backgroundprocesses = [p for p in backgroundprocesses if good_processes[p]]

      #write the actual combine cards
      print("Creating Combine card file",outputpath + band+ year+".txt")
      f = open(outputpath + "/" + band + year+ ".txt","w")
      f.write("imax " + str(1) + "\n") #number of channels
      f.write("jmax " + "*" + "\n") #number of backgroundsstr(len(backgroundprocesses))
      f.write("kmax " + "*" + "\n") #number of nuisance parametersstr(len(uncertainties))
      # f.write("----------\n")
      # f.write("shapes * * $PROCESS.root $CHANNEL/DNN_NNOutput $CHANNEL/DNN_NNOutput_$SYSTEMATIC\n")
      # f.write("----------\n")
      # f.write("bin         " + band + "\n")
      f.write("----------\n")


      f.write(
          "shapes data_obs {ch}_{era} {absolutepathname}Run3_{era}/{file} {ch}/DNN_NNOutput\n".format(
              ch=band,
              file= "Data_Muon.root",
              era=year,
              absolutepathname=absolutepathname,
          )
      )
      for proc in signalprocesses + backgroundprocesses:
          f.write(
              "shapes {proc} {ch}_{era} {absolutepathname}Run3_{era}/{file} {ch}/DNN_NNOutput {ch}/DNN_NNOutput_$SYSTEMATIC\n".format(
                  proc=proc,
                  ch=band,
                  file=process_files.get(proc, proc + ".root"),
                  era=year,
                  absolutepathname=absolutepathname,
              )
          )
      f.write("----------\n")
      f.write("bin         " + band + "_" + year + "\n")

      data = ROOT.TFile.Open(histogramfilepath+"Data_Muon.root")
      datahistogram = data.Get("Signal_Fit_VBF/DNN_NNOutput")
      f.write("observation " + "-1" + "\n")#TODO:Fix this, data currently has value str(datahistogram.Integral()) + "\n")
      f.write("----------\n")

      ##assemble strings for lines
      print("Assembling lines for Combine card ",bandname)
      systLines = []
      maxLength = 0
      # print("uncertainties",uncertainties)
      for i in range(0, len(uncertainties)):
        systLines.append(uncertainties[i][0])
        maxLength = max(maxLength, len(systLines[i]))

      maxLength2 = 0
      for i in range(0, len(systLines)): #align uncertainty names, then assemble uncertainty types
        while len(systLines[i]) < (maxLength + 3):
          systLines[i] += " "
        systLines[i] += uncertainties[i][1]
        maxLength2 = max(maxLength2, len(systLines[i]))

      for i in range(0, len(systLines)): #align syst types
        while len(systLines[i]) < (maxLength2 + 5):
          systLines[i] += " "

      maxLength2 = len(systLines[0])

      #assemble bin and process block
      allNames = signalprocesses + backgroundprocesses
      allNumbers = []
      for i in range(-len(signalprocesses)+1, 1): #negative and zero numbers for signals
        allNumbers.append(i)
      for i in range (1, len(backgroundprocesses)+1): #positive nonzero numbers for backgrounds
        allNumbers.append(i)
      binLine      = "bin     "
      processLine1 = "process "
      processLine2 = "process "
      rateLine     = "rate    "

      #align bin, process, and rate lines with systematic line length
      while len(binLine) < maxLength2:
        binLine += " "
      while len(processLine1) < maxLength2:
        processLine1 += " "
      while len(processLine2) < maxLength2:
        processLine2 += " "
      while len(rateLine) < maxLength2:
        rateLine += " "

      for i in range(0, len(allNames)): #assemble bin, process, rate, and systematic line entries, then align HERE
        binLine += band + "_" + year
        processLine1 += allNames[i]
        processLine2 += str(allNumbers[i])
        if good_processes[allNames[i]]:
          rateLine += "-1"
        else:
          rateLine += "0 "
        currentLength = max(len(binLine), len(processLine1), len(processLine2), len(rateLine))
        for j in range(0, len(systLines)): #assemble systematic values
          proc_tag = uncertainties[j][3]  # process this syst is tied to (or None)
          if proc_tag is not None:
            # {process}-expanded systematic: value only for matching process
            if allNames[i] in proc_tag:#proc_tag == allNames[i]:
              systLines[j] += uncertainties[j][2]
            else:
              systLines[j] += "-"+" "*(len(uncertainties[j][2])-1)
          elif (uncertainties[j][0] not in xsecdict.keys()) or (uncertainties[j][0]==allNames[i]):
            # print(uncertainties[j][2],uncertainties[j][0])
            systLines[j] += uncertainties[j][2]
          else:
            systLines[j] += "-"+" "*(len(uncertainties[j][2])-1)
          currentLength = max(currentLength, len(systLines[j]))

        #align all lines with extra space
        currentLength += 5

        while len(binLine) < currentLength:
          binLine += " "

        while len(processLine1) < currentLength:
          processLine1 += " "

        while len(processLine2) < currentLength:
          processLine2 += " "

        while len(rateLine) < currentLength:
          rateLine += " "

        for j in range(0, len(systLines)):
          while len(systLines[j]) < currentLength:
            systLines[j] += " "

      print("Writing Combine Card values")
      f.write(binLine + "\n")
      f.write(processLine1 + "\n")
      f.write(processLine2 + "\n")
      f.write(rateLine + "\n")
      f.write("----------\n")

      for i in range(0, len(systLines)):
        f.write(systLines[i] + "\n")

      #add MC statistics evaluation
      f.write("\n")
      f.write("* autoMCStats 10 0 1\n")
      # f.write(
      #     "DY_norm_Hard_{era} rateParam {ch}_{era} "
      #     "DYto2Mu_MLL105To160_2J_Hard 1 [0,5.]\n".format(ch=band, era=year)
      # )
      # for proc in ("DYto2Mu_MLL105To160_2J_PU1", "DYto2Mu_MLL105To160_2J_PU2"):
      #   f.write(
      #       "DY_norm_PU_{era} rateParam {ch}_{era} "
      #       "{proc} 1 [0,5.]\n".format(ch=band, era=year, proc=proc)
      #   )

      f.close()
    #   DY_norm rateParam * DYto2Mu_MLL105To160 1 [0,10]
    # EWK_norm rateParam * EWK_2Mu2J_MLL_105to160_herwig 1 [0,10]
    # combineCards.py y2022=Signal_Fit_VBF2022.txt y2022EE=Signal_Fit_VBF2022EE.txt y2023=Signal_Fit_VBF2023.txt y2023BPix=Signal_Fit_VBF2023BPix.txt y2024=Signal_Fit_VBF2024.txt y2025=Signal_Fit_VBF2025.txt > Signal_Fit_VBF.txt


if __name__ == "__main__":
    main()
