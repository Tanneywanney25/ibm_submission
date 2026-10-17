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
 ['unsubscribe','remove-alerts'],['How do I stop alerts?','remove-alerts'],['turn notifications off','remove-alerts'],
 ['Will I stay signed in?','remember'],['remember me','remember'],
 ['How can I see my landlord?','landlord'],['Who owns my building?','landlord'],
 ['I want to write an email to my landlord','draft-message'],['Draft a notice','draft-message'],
 ['Where is the inspection queue?','inspector'],['download csv','inspector'],['open the live monitor','replay'],
 ['How can I file a heat complaint?','no-heat'],['My heat died','no-heat'],['no hot water','no-heat'],
 ['What temperature is required at night?','heat-rules'],['heat season','heat-rules'],
 ['Is this a live photo?','imagery'],['satellite photo','imagery'],
 ['Do you store my questions?','privacy'],['Will I definitely lose heat?','limitations'],
 ['I smell gas','emergency'],['carbon monoxide alarm','emergency'],['fire no heat','emergency'],
 ['3000410007','look-up'],['BBL 3000410007','look-up'],['What is a BBL?','bbl']
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
console.log('PASS:',cases.length,'natural-language examples, all',items.length,'published questions, unknown questions, follow-ups, private input, safe links and building context.');
