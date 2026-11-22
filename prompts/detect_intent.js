// Detect Intent (rules) - deterministic pre-check that runs BEFORE the AI agent (workflow 03).
// Small local models follow one short, explicit note much better than a long system prompt, so this step spots
// clear signals and appends a "[NOTE FOR ASSISTANT: ...]" to the message. It also returns `intent` flags that the
// guaranteed-escalation step after the agent uses (so escalation never depends on the model alone).
// Unit-tested in tests/test_guardrails.py (runs this exact code with Node).
const msg = String($json.chatInput || '');
const m = msg.toLowerCase();
const notes = [];

// --- language: Hindi script, or Hinglish (Hindi written in English letters) -------------------------------
const HINGLISH = ['kya', 'hai', 'hain', 'mera', 'meri', 'mere', 'mujhe', 'kab', 'kaise', 'kyu', 'kyun', 'nahi', 'nahin',
  'aayega', 'aaya', 'ayega', 'chahiye', 'karo', 'karna', 'bhai', 'yaar', 'abhi', 'jaldi', 'paisa', 'paise', 'wapas',
  'vapas', 'kitna', 'kitne', 'gaya', 'hua', 'ho', 'tak', 'ke', 'ki', 'ka', 'aur', 'bhi', 'milega', 'batao', 'kab tak'];
const words = m.split(/[^a-z]+/).filter(Boolean);
const hinglishHits = words.filter(w => HINGLISH.includes(w)).length;
const language = /[ऀ-ॿ]/.test(msg) ? 'hi' : (hinglishHits >= 2 ? 'hinglish' : 'en');
if (language === 'hi') notes.push('The customer writes in Hindi: reply in simple Hindi (Devanagari). Search the knowledge tools in English.');
if (language === 'hinglish') notes.push('The customer writes in Hinglish: reply in friendly Hinglish (Hindi in English letters). Search the knowledge tools in English.');

// --- anger, sarcasm, shouting -------------------------------------------------------------------------------
const ANGRY = /manager|human|real person|complain|worst|third time|angry|furious|ridiculous|fed up|cheat|fraud|useless|pathetic|scam|consumer court|bad review|bakwas|bakwaas|bekaar|bekar|ghatiya|faltu|dhokha|chor|kitni baar|third class|bahut bura|गुस्सा|बकवास|धोखा|मैनेजर|😡|🤬|😤/;
const PRAISE = '(wow|great|amazing|awesome|fantastic|brilliant|superb|love (it|this|waiting)|thanks a lot|thank you so much|so fast|super fast|bravo|well done|nice job|great job)';
const PROBLEM = '(still|again|late|never|not|no one|nobody|waiting|delay|delayed|weeks?|lost|missing)';
const SARCASM = new RegExp(`\\b${PRAISE}\\b[^.!?]{0,80}\\b${PROBLEM}\\b|\\b${PROBLEM}\\b[^.!?]{0,80}\\b${PRAISE}\\b|🙄|🙃|👏👏|/s\\b`);
const letters = msg.replace(/[^A-Za-z]/g, '');
const shouting = /!!!/.test(msg) || (letters.length >= 12 && letters.replace(/[^A-Z]/g, '').length / letters.length > 0.7);
const sarcastic = SARCASM.test(m);
const angry = ANGRY.test(m) || sarcastic || shouting;
if (angry)
  notes.push((sarcastic ? 'The customer is being sarcastic - they are actually upset. ' : '') +
    'The customer is upset or asks for a human: apologise, look up the order if an order ID is given, then you MUST call escalate_to_human and give the ticket ID.');

// --- refund over the limit -----------------------------------------------------------------------------------
const refund = /refund|money back|paise? wapas|paisa wapas|paise? vapas|paisa vapas|रिफंड|पैसे वापस/.test(m);
if (refund && /ut\d{4}/.test(m))
  notes.push('Refund request: call order_lookup; if the order amount is more than Rs 5000 you MUST call escalate_to_human (you cannot approve it) and give the ticket ID.');

// --- stock, returns, offers, out of scope --------------------------------------------------------------------
if (/\b(stock|in stock|available|availability|restock|reorder|purchase order|inventory|low stock|milega|available hai)\b/.test(m) && !/stock market/.test(m))
  notes.push('This is about stock or purchase orders: call inventory_expert with the full question (in English) and pass its answer on. Do not guess availability.');
if (/return|exchange|does not fit|doesn't fit|too (small|big|tight|loose)|wrong size|wapas|vapas|chota|bada|fit nahi/.test(m) && /ut\d{4}/.test(m))
  notes.push('Return question about an order: call order_lookup for the order AND faq_knowledge for the return and refund policy, then answer with both (no stock check needed).');
if (/diwali|discount|coupon|promo|offer|sale|code|gift card|loyalty/.test(m) && !/python|javascript|script|program/.test(m))
  notes.push('Offers and coupon codes: call website_knowledge first and give ONLY codes that appear in its result. Never invent a code.');
if (/python|javascript|java |code|script|program|homework|essay|poem|recipe|weather|cricket|movie|stock market|bitcoin/.test(m)
    && !/order|ut\d{4}|return|refund|size|deliver|kurta|shirt|jeans|hoodie|in stock|restock|low stock|coupon|discount/.test(m))
  notes.push('This is NOT about UrbanThread. Do not answer it and do not write code: reply that you can only help with UrbanThread orders, returns, sizes, delivery, offers and stock.');

// --- identity check for orders: order ID + last 4 digits of the phone ----------------------------------------
const oid = (msg.toUpperCase().match(/UT\d{4}/) || [''])[0];
const phone = (msg.replace(/[\s-]/g, '').match(/(\+?91)?[6-9]\d{9}/) || [''])[0];
const noOid = msg.replace(/UT\d{4}/gi, ' ');
const last4 = phone ? phone.slice(-4) : ((noOid.match(/(?:^|\D)(\d{4})(?!\d)/) || ['', ''])[1]);
if (oid && last4) notes.push(`Call order_lookup with order_id ${oid} and phone_last4 ${last4}.`);
else if (oid) notes.push(`Call order_lookup with order_id ${oid} and an empty phone_last4; it will tell you to ask for the last 4 digits of the phone number. Never share order details before they are verified.`);
else if (last4 && /^\D*\d{4}\D*$/.test(msg.trim())) notes.push(`The customer sent 4 digits (${last4}): these are the last 4 digits of their phone for the order ID mentioned earlier in this chat. Call order_lookup with that order ID and phone_last4 ${last4}.`);

// --- flags for the guaranteed-escalation step after the agent ------------------------------------------------
const name = (msg.match(/\b(?:i am|i'm|my name is|this is|main)\s+([A-Z][a-z]+)/) || ['', ''])[1];
const intent = { escalate: angry, sarcastic, refund, language, order_id: oid, phone, last4, name, original: msg };
return [{ json: { ...$json, intent,
  chatInput: notes.length ? msg + '\n\n[NOTE FOR ASSISTANT: ' + notes.join(' ') + ']' : msg } }];
