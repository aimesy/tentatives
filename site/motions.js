// Shared motion taxonomy for the statewide tentative-rulings viewer.
//
// This follows the SFSC viewer's hierarchy: a raw calendar caption is
// classified into a normalized motion type (and, where useful, subtype), then
// rolled up into a broad category. Rules are deliberately caption-driven so a
// matter is classified by what it is, not by the county or department that
// happened to hear it. Statewide family-law vocabulary is included because it
// is present in this corpus but outside the SFSC civil viewer's scope.

const rule = (test, type, category, subtype = null) => ({ test, type, category, subtype });

function summarySubtype(text) {
  const judgment = /\bsummary\s+judg(?:e)?ment\b|\bmsj\b/i.test(text);
  const adjudication = /\bsummary\s+adjudication\b/i.test(text);
  if (judgment && adjudication) return "Combined Summary Judgment/Adjudication";
  if (adjudication) return "Summary Adjudication";
  return judgment ? "Summary Judgment" : null;
}

function compelType(text) {
  if (/\barbitration\b/i.test(text)) return null;
  if (/\bfurther\b.*\b(?:response|production|interrog|admission|document)\b|\bfurther responses?\b/i.test(text)) {
    return "Compel Further Responses";
  }
  if (/\bdeposition\b|\bpmq\b|\bpmk\b|\bperson most\b/i.test(text)) return "Compel Deposition";
  if (/\b(?:document )?production\b|\bproduce\s+documents?\b|\bmedical records?\b/i.test(text)) return "Compel Production";
  if (/\binterrogator\w+\b|\bform interrogator|\bspecial interrogator/i.test(text)) return "Compel Interrogatories";
  if (/\brequests?\s+for\s+admission|\brfas?\b/i.test(text)) return "Compel RFAs";
  if (/\bsubpoena\b/i.test(text)) return "Compel Subpoena Compliance";
  if (/\bresponses?\s+to\b|\banswers?\b/i.test(text)) return "Compel Initial Responses";
  return "Compel (other)";
}

const PROBATE_RULES = [
  rule(/\baccounting\s+petition\b/i, "Accounting Petition", "Probate"),
  rule(/\b(?:future|first|second|annual|final)\s+account(?:ing)?\b|\bfiling\s+of\s+(?:first|final)\s+account\b|\bstatus of account\b/i,
    "Account / Status of Account", "Probate"),
  rule(/\bpetition\s+for\s+(?:letters\s+(?:of\s+administration|testamentary)|probate\s+of\s+(?:the\s+)?will)\b|\bpetition to administer estate\b/i,
    "Petition for Letters / Probate of Will", "Probate"),
  rule(/\bpetition\s+for\s+(?:spousal|domestic partner)\s+property\b/i,
    "Spousal / Domestic Property Petition", "Probate"),
  rule(/\bpetition\s+for\s+instructions\b/i, "Petition for Instructions", "Probate"),
  rule(/\bpetition\s+to\s+(?:appoint|remove|substitute)\s+(?:successor\s+)?trustee\b|\bappointment\s+of\s+(?:co-?)?trustee\b|\bconfirm trustee\b/i,
    "Trustee Appointment / Removal", "Probate"),
  rule(/\bspecial\s+needs\s+(?:trust|tr\.?)\b|\bsnt\b/i, "Special Needs Trust", "Probate"),
  rule(/\b(?:establish|terminate|modify|reform|fund)\s+(?:the\s+|an?\s+)?trust\b|\binter[\s-]?vivos\s+trust\b/i,
    "Trust Establish / Terminate / Modify", "Probate"),
  rule(/\bdetermin(?:e|ing|ation\s+of)\s+(?:distribution|heirship|entitlement)\s+rights?\b|\bsuccession to (?:real |personal )?property\b/i,
    "Determine Distribution Rights", "Probate"),
  rule(/\b(?:report\s+of\s+sale|petition\s+to\s+confirm\s+sale|sale of real property)\b/i,
    "Sale of Real Property", "Real Estate"),
  rule(/\bconservatorship\b|\bguardianship\b|\bpetition to appoint guardian\b/i,
    "Conservatorship / Guardianship", "Probate"),
  rule(/\binventory\s+(?:and|&)\s+appraisal\b|\bfiling\s+of\s+inventory\b|\bobjections?\s+to\s+inventory\b/i,
    "Inventory / Appraisal", "Probate"),
  rule(/\bfinal distribution\b|\bdistribution of estate\b|\bpetition for distribution\b/i,
    "Distribution / Discharge", "Probate"),
  rule(/\bstatus\s+(?:report|hearing|conference|review|of\s+administration|of\s+the\s+estate)\b|\bannual status\b|\bcompliance\s+status\b/i,
    "Status / Compliance Hearing", "Procedural"),
];

const FAMILY_RULES = [
  rule(/\bdomestic violence\b|\bdvro\b|\brestraining order\b.*\b(?:family|domestic|harassment)\b/i,
    "Domestic Violence Restraining Order", "Family Law"),
  rule(/\bchild custody\b|\bvisitation\b|\bparenting time\b|\bmove[ -]?away\b/i,
    "Child Custody / Visitation", "Family Law"),
  rule(/\bchild support\b/i, "Child Support", "Family Law"),
  rule(/\bspousal (?:or partner )?support\b|\bpartner support\b/i, "Spousal / Partner Support", "Family Law"),
  rule(/\bparentage\b|\bpaternity\b/i, "Parentage", "Family Law"),
  rule(/\bdivision of (?:community )?property\b|\bproperty division\b|\bcommunity property\b/i,
    "Property Division", "Family Law"),
  rule(/\brequest for order\b|\brfo\b/i, "Request for Order (other)", "Family Law"),
];

const CIVIL_RULES = [
  rule(/\banti[-\s]?slapp\b|\bccp\s*§?\s*425\.16\b|\bspecial\s+motion\s+to\s+strike\b/i,
    "Special Motion to Strike (CCP 425.16/Anti-SLAPP)", "Dispositive"),
  rule(/\bdemurrer\b/i, "Demurrer", "Pleadings"),
  rule(/\bmotion\s+(?:(?:to|for|and|of)\s+)?(?:notice\s+)?(?:to\s+)?strike\b|\bmtn to strike\b/i,
    "Motion to Strike", "Pleadings"),
  rule(/\bsummary\s+judg(?:e)?ment\b|\bsummary\s+adjudication\b|\bsummary motion\b|\bmsj\b/i,
    "Summary Judgment / Adjudication", "Dispositive", summarySubtype),
  rule(/\bjudg(?:e?ment|mnt)\s+on\s+(?:the\s+)?pleadings?\b/i, "Judgment on the Pleadings", "Pleadings"),
  rule(/\bcompel\s+arbitration\b|\bpetition to compel arbitration\b/i, "Compel Arbitration", "Arbitration"),
  rule(/\bdeem(?:ed|ing)?\b[\s\S]*?\badmit(?:ted)?\b|\bestablish(?:ing)?\s+admissions?\b/i,
    "Deem RFAs Admitted", "Discovery"),
  rule(/\breopen(?:ing)?\s+(?:of\s+)?discovery\b/i, "Reopen Discovery", "Discovery"),
  rule(/\b(?:mental|physical|independent\s+medical)\s+examination\b|\bime\b/i,
    "Mental / Medical Examination", "Discovery"),
  rule(/\bdiscovery\s+referee\b|\breport\s+of\s+(?:discovery\s+)?referee\b/i,
    "Discovery Referee", "Discovery"),
  rule(/\bcompel(?:ling|s|led)?\b|^\s*discovery\s*$|\bmotion for discovery\b|\bdiscovery\s+cutoff\b/i,
    compelType, "Discovery"),
  rule(/\b(?:quash|quashing)\b[^.]*\bsubpoenas?\b|\bquashing\s+(?:notice\s+)?(?:of\s+)?deposition\b/i,
    "Quash Subpoena", "Discovery"),
  rule(/\b(?:motion|mtn|ntc\s+of\s+mtn)\s+(?:and\s+(?:motion|mtn)\s+)?(?:to\s+)?quash\b|\border\s+quashing\b/i,
    "Quash Service / Jurisdiction", "Pleadings"),
  rule(/\bprotective order\b|\bretain confidentiality\b/i, "Protective Order", "Discovery"),
  rule(/\brelief\s+from\s+(?:the\s+)?waiver\s+of\s+objections?\b/i, "Relief from Waiver", "Discovery"),
  rule(/\baugment(?:\/amend)?\s+(?:expert\s+)?(?:disclosure|witness)|\bleave\s+to\s+augment\b/i,
    "Augment Expert Disclosure", "Discovery"),
  rule(/\bdisqualif(?:y|ication|ying)\b(?![^.]*\b(?:judge|judicial|juror)\b)/i,
    "Disqualify Counsel", "Attorney"),
  rule(/\b(?:substitut(?:e|ion|ing)|change)\s+(?:of\s+)?(?:attorney|attorneys|counsel)\b/i,
    "Substitution of Attorney", "Attorney"),
  rule(/\bpro hac vice\b/i, "Pro Hac Vice", "Attorney"),
  rule(/\brelieve(?:d)?\s+as\s+(?:attorney|counsel)\b|\bwithdraw(?:al)?\s+(?:as|of)\s+(?:attorney|counsel)\b|\bmotion\s+(?:to\s+)?be\s+relieved\b|\battorney withdrawal\b/i,
    "Counsel — Withdraw / Be Relieved", "Attorney"),
  rule(/\battorneys?[’']?s?\s*fees?\b|\batty\s*fees?\b|\btax\s+(?:memo\s+of\s+)?costs\b|\bstrike\s+(?:memo\s+of\s+)?costs\b/i,
    "Attorney Fees / Costs", "Fees & Costs"),
  rule(/\bsanctions?\b/i, "Sanctions", "Sanctions"),
  rule(/\bsett?ing aside\b.*\b(?:default|judgment|order|dismissal)\b|\bset aside\b.*\b(?:default|judgment|order|dismissal)\b|\bvacat(?:e|ing)\b.*\b(?:default|judgment|order|renewal|dismissal)\b|\brelief\s+from\s+default\b/i,
    "Set Aside / Vacate", "Post-Trial"),
  rule(/\bdefault\s+(?:hearing|prove[\s-]?up|judgment)\b|\bprove[\s-]?up\s+hearing\b/i,
    "Default Judgment / Prove-Up", "Post-Judgment"),
  rule(/\bclaim of exemption\b/i, "Claim of Exemption", "Post-Judgment"),
  rule(/\bright to attach\b|\bwrit of attachment\b|\battachment order\b/i, "Right to Attach", "Post-Judgment"),
  rule(/\bpetition\b.*\bconfirm\b.*\barb(?:itration)?\b|\bconfirm arb(?:itration)? award\b/i,
    "Petition to Confirm Arbitration Award", "Arbitration"),
  rule(/\bvacate\b[\s\S]{0,60}\barbitration\s+award\b|\bcorrect\b[\s\S]{0,40}\barbitration\s+award\b/i,
    "Vacate Arbitration Award", "Arbitration"),
  rule(/\barbitration\b/i, "Arbitration (other)", "Arbitration"),
  rule(/\bgood faith\s+(?:settlement|determination|finding)\b|\bccp\s*§?\s*877\.6\b/i,
    "Good Faith Settlement", "Settlement"),
  rule(/\bminor['’]?s compromise\b|\bcompromise of claim.*\bminor\b/i,
    "Minor's Compromise", "Settlement"),
  rule(/\bfinal\s+(?:approval|fairness)\b|\bpreliminary approval\b|\bclass action settlement\b|\bclass settlement\b|\bapprove\s+(?:the\s+)?settlement\b/i,
    "Approve Settlement", "Settlement"),
  rule(/\benforce\s+(?:the\s+)?settlement\b|\bmotion to enforce\b|\bccp\s*§?\s*664\.6\b/i,
    "Enforce Settlement", "Settlement"),
  rule(/\bconsolidat(?:e|ion|ing)\b/i, "Consolidate", "Procedural"),
  rule(/\bsever(?:ance|ed|ing)?\b|\bbifurcat(?:e|ed|ing|ion)\b/i, "Sever / Bifurcate", "Procedural"),
  rule(/\bforum non conveniens\b/i, "Forum Non Conveniens", "Pleadings"),
  rule(/\bstay(?:s|ing|ed)?\b/i, "Stay", "Procedural"),
  rule(/\bdismiss(?:al)?\b|\bdimiss\b/i, "Dismiss", "Pleadings"),
  rule(/\breceiver\b/i, "Receiver", "Procedural"),
  rule(/\b(?:preliminary|mandatory)\s+inju\w+\b|\b(?:temporary\s+|request for\s+)?restraining\s+order\b|\btro\b/i,
    "Injunction / TRO", "Injunctive"),
  rule(/\blis pendens\b|\bexpunge\b/i, "Lis Pendens / Expunge", "Real Estate"),
  rule(/\bnew trial\b/i, "New Trial", "Post-Trial"),
  rule(/\breconsider(?:ation)?\b/i, "Reconsideration", "Post-Trial"),
  rule(/\bclass certificat(?:ion|e)\b|\bcertify (?:a )?class\b/i, "Class Certification", "Class Action"),
  rule(/\bintervene\b|\bintervention\b/i, "Intervene", "Procedural"),
  rule(/\bleave\s+to\s+(?:to\s+)?file\b|\bleave\s+to\s+amend\b|\bfile\s+(?:an?\s+)?(?:first|second|third|fourth|amended).*\b(?:complaint|petition|answer|pleading)\b/i,
    "Leave to Amend / File", "Pleadings"),
  rule(/\bsale of dwelling\b|\bsale of (?:real )?property\b/i, "Sale of Dwelling / Property", "Real Estate"),
  rule(/\bcharging\s+(?:order|judgment\s+debtor|partnership\s+interest)\b/i, "Charging Order", "Post-Judgment"),
  rule(/\brenewal of judgment\b/i, "Renewal of Judgment", "Post-Judgment"),
  rule(/\bcontempt\b/i, "Contempt", "Post-Judgment"),
  rule(/\bcontinuance\b|\badvance\s+(?:the\s+)?hearing\b|\bcontinue\s+(?:the\s+)?(?:hearing|trial|case)\b/i,
    "Continuance / Advance", "Procedural"),
  rule(/\b(?:to |motion (?:to )?|under )seal\b|\bfile\s+(?:records\s+)?under\s+seal\b/i, "Sealing", "Procedural"),
  rule(/\bchange of venue\b|\btransfer (?:of )?venue\b|\bmotion to transfer\b/i, "Venue", "Pleadings"),
  rule(/\bwrit\s+of\s+(?:administrative\s+)?manda(?:te|mus)\b|\bpetition\s+for\s+(?:peremptory\s+)?writ\b/i,
    "Writ of Mandate", "Writ"),
  rule(/\bwrit of possession\b/i, "Writ of Possession", "Real Estate"),
  rule(/\b(?:entry\s+of|enter(?:ing)?)\s+(?:consent\s+|monetary\s+)?judgment\b|\bjudgment\s+pursuant\s+to\s+stipulation\b/i,
    "Entry of Judgment", "Post-Judgment"),
  rule(/\bstructured settlement\b/i, "Structured Settlement Transfer", "Settlement"),
  rule(/\btrial\s+preference\b|\bpreferential\s+setting\b/i, "Trial Preference / Setting", "Procedural"),
  rule(/\bre-?classif(?:y|ication|ying)\b|\bcorrect\s+case\s+classification\b/i, "Reclassification", "Procedural"),
  rule(/\bjoinder\s+of\s+(?:additional\s+)?parties\b/i, "Joinder of Parties", "Procedural"),
  rule(/\bsubstitut(?:e|ing|ion)\s+(?:plaintiff|defendant|petitioner|respondent|successor)\b/i,
    "Substitute Party", "Procedural"),
  rule(/\bvexatious\s+litigant\b|\bprefiling\s+order\b/i, "Vexatious Litigant", "Procedural"),
  rule(/\bname change\b|\bpetition for change of name\b/i, "Name Change", "Special Proceedings"),
  rule(/\bcase management\b|\bcmc\b/i, "Case Management", "Procedural"),
  rule(/\border to show cause\b|\bosc\b/i, "Order to Show Cause", "Procedural"),
  rule(/\bstatus\s+(?:conference|hearing|review)\b|\breview\s+regarding\s+status\b|\bcompliance hearing\b|\benforcement hearing\b/i,
    "Status / Compliance Hearing", "Procedural"),
];

const GENERIC_RULES = [
  // Keep this last: specific civil petitions (writ, arbitration, settlement)
  // must win before the probate-style catch-all.
  rule(/\bpetition\b/i, "Petition (other)", "Probate"),
];

const ALL_RULES = [...PROBATE_RULES, ...FAMILY_RULES, ...CIVIL_RULES, ...GENERIC_RULES];

const JOINDER_FRAMING = [
  /^\s*(?:notice\s+(?:of\s+)?)?joinder\s+(?:in|to)\s+/i,
  /\(joinder\)\s*$/i,
];

function stripJoinderFraming(value) {
  let text = value;
  for (const pattern of JOINDER_FRAMING) text = text.replace(pattern, "").trim();
  return text;
}

function fallbackForDivision(division) {
  const value = String(division || "").toLowerCase();
  if (/probate|trust|estate|guardianship|conservatorship/.test(value)) {
    return { category: "Probate", type: "Probate Matter", subtype: null };
  }
  if (/family|domestic/.test(value)) {
    return { category: "Family Law", type: "Family Law Matter", subtype: null };
  }
  return { category: "Other", type: "Miscellaneous", subtype: null };
}

export function classifyMotion(value, division = "") {
  const text = stripJoinderFraming(String(value || "").replace(/\s+/g, " ").trim());
  if (!text) return fallbackForDivision(division);
  for (const entry of ALL_RULES) {
    const matches = typeof entry.test === "function" ? entry.test(text) : entry.test.test(text);
    if (!matches) continue;
    const type = typeof entry.type === "function" ? entry.type(text) : entry.type;
    if (!type) continue;
    const subtype = typeof entry.subtype === "function" ? entry.subtype(text) : entry.subtype;
    return { category: entry.category, type, subtype: subtype || null };
  }
  return fallbackForDivision(division);
}

export function motionTextForClassification(row) {
  const caption = String(row?.motion_type || "").trim();
  if (caption) return caption;
  return motionFallbackTextForClassification(row);
}

export function motionFallbackTextForClassification(row) {
  // body_text is the parser-defined narrative between the case header and the
  // disposition, and is therefore safer than classifying the entire ruling.
  const body = String(row?.body_text || "").trim();
  if (body) return body.slice(0, 1200);
  return String(row?.full_text || "").trim().slice(0, 1200);
}
