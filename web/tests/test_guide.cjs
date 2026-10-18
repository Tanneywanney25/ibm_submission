/* node web/tests/test_guide.cjs — no npm install required */
const assert=require('node:assert/strict');
const guide=require('../static/guide.js');
const {items}=require('../static/guide-content.json');
const cases=[
 ['How can I check my building?','look-up'],['find my building','look-up'],['look up an address','look-up'],
 ['Show me the map','map'],['How can I filter the map?','map'],['How do I see all five boroughs?','map'],
 ['What does a hexagon mean?','hexagons'],['Why do hexagons have different heights?','heights'],
 ['Why are some hexagons taller?','heights'],['what does height mean','heights'],
 ['Why are some buildings darker blue?','colors'],['Explain map colours','colors'],
 ['what is my risk score','winter-risk'],['what is winter risk','winter-risk'],['Explain cold day risk','cold-day'],
 ['Can I trust these numbers?','calibration'],['How accurate is this?','calibration'],
 ['Why is my building not individually ranked?','unranked'],['Where is the data from?','data'],
 ['Why can I see buildings but no hexagons?','unranked'],['Does no color mean no complaints?','unranked'],
 ['What are the gray buildings?','unranked'],['Why are there blank areas on the map?','unranked'],
 ['Where do I sign in?','sign-in'],['Can I use this without an account?','sign-in'],
 ['How can I get alerts?','alerts'],['notify me','alerts'],['How do I save my building?','alerts'],
 ['How do I stop alerts?','remove-alerts'],['turn notifications off','remove-alerts'],
 ['Will I stay signed in?','remember'],['remember me','remember'],
 ['How can I see my landlord?','landlord'],['Who owns my building?','landlord'],
 ['I want to write an email to my landlord','draft-message'],['Draft a notice','draft-message'],
 ['Where is the inspection queue?','inspector'],['download csv','inspector'],['open the live monitor','replay'],
 ['How can I file a heat complaint?','no-heat'],['My heat died','no-heat'],['no hot water','no-heat'],
 ['What temperature is required at night?','heat-rules'],['heat season','heat-rules'],
 ['Is this a live photo?','imagery'],['satellite photo','imagery'],
 ['Do you store my questions?','privacy'],['Will I definitely lose heat?','limitations'],
 ['I smell gas','emergency'],['carbon monoxide alarm','emergency'],['fire no heat','emergency'],
 ['3000410007','look-up'],['BBL 3000410007','look-up'],['What is a BBL?','bbl'],
 ['How do I contact the team?','team-contact'],['How can I reject cookies?','cookies'],['Stop the newsletter','newsletter']
];
for(const [question,expected] of cases)assert.equal(guide.match(question,items)?.id,expected,question);
for(const item of items)assert.equal(guide.match(item.question,items)?.id,item.id,item.question);
for(const question of ['What is the capital of France?','Write me a poem','calculate 2 plus 2',''])assert.equal(guide.match(question,items),null,question);
assert.equal(guide.match('How do I do that?',items,'alerts').id,'alerts');
assert.equal(guide.extractBBL('BBL: 3000410007'),'3000410007');
assert.equal(guide.extractBBL('my phone is 2125551234'),null);
assert.equal(guide.privateQuestion('email me at me@example.test'),true);
assert.equal(guide.privateQuestion('unit #12 has no heat'),true);
assert.equal(guide.privateQuestion('my phone is 2125551234'),true);
assert.equal(guide.privateQuestion('How can I get email alerts?'),false);
assert.equal(guide.privateQuestion('BBL 3000410007'),false);
for(const href of ['javascript:alert(1)','//evil.test','/api/account/remove','/api/auth/logout','https://evil.test','/\\evil.test'])assert.equal(guide.safeLink(href),false,href);
for(const item of items)for(const link of [...item.links,...item.sources])assert.equal(guide.safeLink(link.href),true,link.href);
assert.equal(guide.contextualLink('/building?as=landlord#draft','3000410007'),'/building?as=landlord&bbl=3000410007#draft');
assert.equal(guide.contextualLink('/map','3000410007'),'/map');
assert.equal(guide.contextualLink('/building','<script>'),'/building');
for(const [question,ids] of [
 ['email',['alerts','newsletter','sign-in','draft-message']],
 ['emial',['alerts','newsletter','sign-in','draft-message']],
 ['unsubscribe',['remove-alerts','newsletter']],['stop emails',['remove-alerts','newsletter']],
 ['unsuscribe',['remove-alerts','newsletter']],['risk',['winter-risk','cold-day','calibration']],
 ['riks',['winter-risk','cold-day','calibration']],['contact',['team-contact','landlord','draft-message']],
 ['map colors and heights',['heights','colors']]
]){
  const result=guide.interpret(question,items);
  assert.equal(result.answer,null,question);
  assert.deepEqual(result.suggestions.map(i=>i.id),ids,question);
}
for(const [question,expected] of [
 ['how do i loggin','sign-in'],['buidling','look-up'],['find my bilding','look-up'],
 ['map coloers','colors'],['why hexgons so tal','heights'],['get notfications','alerts'],
 ['show me a satelite pic','imagery'],['can i see pictures','imagery'],['winter riks','winter-risk']
]){
  const result=guide.interpret(question,items);
  assert.equal(result.answer,null,'Uncertain spelling should ask first: '+question);
  assert.ok(result.suggestions.some(i=>i.id===expected),question);
  assert.ok(result.suggestions.length<=3,question);
  assert.equal(new Set(result.suggestions.map(i=>i.id)).size,result.suggestions.length);
}
for(const question of ['write me a poem','buy me a car','calculate 2 plus 2']){
  const result=guide.interpret(question,items);assert.equal(result.answer,null);assert.equal(result.suggestions.length,0);
}
assert.ok(guide.rank('email',items).filter(r=>r.hits).some(r=>r.item.id==='newsletter'));
assert.equal(guide.interpret('my email is person@example.test',items).suggestions.length,0);
assert.equal(guide.match('my heat died and I want email alerts',items).id,'no-heat');
assert.equal(guide.match('I smell gas can I unsubscribe',items).id,'emergency');
assert.equal(guide.match('unsubscribe from building alerts',items).id,'remove-alerts');
assert.equal(guide.match('unsubscribe from newsletter',items).id,'newsletter');
const mixed=guide.interpret('help with map and alerts',items);
assert.equal(mixed.answer,null);assert.ok(mixed.suggestions.some(i=>i.id==='map'));assert.ok(mixed.suggestions.some(i=>i.id==='alerts'));
console.log('PASS:',cases.length,'natural-language examples, all',items.length,'published questions, unknown questions, follow-ups, private input, safe links and building context.');
console.log('PASS: ambiguous wording offers multiple choices; typos, synonyms and word transpositions suggest published questions; unrelated/private inputs do not invent answers.');
