import {test,expect,Page,APIRequestContext} from '@playwright/test';
const server='http://127.0.0.1:9635';
async function reset(request:APIRequestContext){const r=await request.post(server+'/__test__/reset');expect(r.ok()).toBeTruthy();return r.json();}
async function login(page:Page,user='owner-a'){await page.goto('/');await page.getByLabel('Username',{exact:true}).fill(user);await page.getByLabel('Password',{exact:true}).fill('a-good-test-password');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.getByRole('link',{name:'Review Inbox',exact:true})).toBeVisible();await expect(page.getByRole('combobox',{name:'Profile',exact:true})).not.toHaveValue('');}
async function review(page:Page){await page.getByRole('link',{name:'Review Inbox',exact:true}).click();await expect(page.locator('.candidate-button').first()).toBeVisible();}

test.beforeEach(async({request})=>{await reset(request);});
test('owner exact approval, blocked relation, verified publication, directed graph and cited answer',async({page})=>{
 await login(page);await review(page);
 await expect(page.getByText('Draft',{exact:true}).first()).toBeVisible();
 await page.locator('.candidate-button').first().click();
 await page.getByRole('button',{name:'Approve entity',exact:true}).click();
 await expect(page.getByText('Approved — awaiting publication',{exact:true}).first()).toBeVisible();
 await page.locator('.candidate-button').filter({hasText:'relation'}).click();
 await page.getByRole('button',{name:'Approve relation',exact:true}).click();
 await expect(page.getByText('Publication blockers',{exact:true})).toBeVisible();
 for(const c of await page.locator('.candidate-row > input').all())await c.check();
 await page.getByRole('button',{name:'Approve selected revisions',exact:true}).click();await expect(page.locator('.candidate-row .tag[data-status=draft]')).toHaveCount(0);
 for(const c of await page.locator('.candidate-row > input').all())await c.check();
 await page.getByRole('button',{name:'Publish selected revisions',exact:true}).click();
 await expect(page.locator('.definition .tag').filter({hasText:'published'})).toBeVisible({timeout:60000});
 await page.getByRole('button',{name:'Refresh candidates',exact:true}).click();
 await expect(page.locator('.candidate-row .tag').filter({hasText:'Published'})).toHaveCount(3);
 await page.getByRole('link',{name:'Central Graph',exact:true}).click();await page.getByRole('button',{name:'Load published graph'}).click();
 await expect(page.locator('.graph-node')).toHaveCount(2);await expect(page.locator('.graph-edge')).toHaveCount(1);
 await page.locator('.graph-edge').focus();await page.keyboard.press('Enter');await expect(page.getByText('Original type: connects')).toBeVisible();
 await page.getByRole('link',{name:'Ask Knowledge AI',exact:true}).click();await page.getByLabel('Your question').fill('Which controllers connect?');await page.getByRole('button',{name:'Ask selected context'}).click();
 await expect(page.getByRole('heading',{name:'Answer',exact:true})).toBeVisible();await expect(page.locator('.citation')).toHaveCount(3);
});
test('stale approval fails visibly; refresh comparison and new-tab CSRF persist',async({page,context})=>{
 await login(page);await review(page);const csrf=(await(await page.request.get('/api/auth/csrf')).json()).csrf_token;
 const rows=await(await page.request.get('/api/versions/'+await page.getByRole('combobox',{name:'Knowledge version',exact:true}).inputValue()+'/candidates')).json();const entity=rows.find((c:any)=>c.kind==='entity');
 const edit=await page.request.patch('/api/candidates/'+entity.id,{headers:{'X-CSRF-Token':csrf},data:{expected_revision:1,payload:{...entity.payload,name:'Corrected test entity'}}});expect(edit.ok()).toBeTruthy();
 await page.getByRole('button',{name:'Approve entity',exact:true}).click();await expect(page.getByRole('alert')).toContainText('Stale candidate revision');
 await page.getByRole('button',{name:'Refresh candidates',exact:true}).click();await expect(page.getByRole('heading',{name:'Revision comparison'})).toBeVisible();
 await page.getByRole('button',{name:'Approve entity',exact:true}).click();await expect(page.getByText('Approved — awaiting publication',{exact:true}).first()).toBeVisible();
 await page.reload();await expect(page.getByRole('button',{name:'Approve entity',exact:true})).toBeVisible();
 const tab=await context.newPage();await tab.goto('/review');await expect(tab.getByRole('button',{name:'Approve entity',exact:true})).toBeVisible();await tab.getByRole('button',{name:'Approve entity',exact:true}).click();await expect(tab.getByText('Approved — awaiting publication',{exact:true}).first()).toBeVisible();await tab.close();
});
test('contributor edits but cannot approve; empty version and manual upload are usable',async({page})=>{
 await login(page,'contributor');await review(page);await expect(page.getByRole('button',{name:'Approve entity',exact:true})).toHaveCount(0);
 await page.getByLabel('Entity name',{exact:true}).fill('Contributor correction');await page.getByRole('button',{name:'Save new draft revision'}).click();await expect(page.getByRole('heading',{name:'Revision comparison'})).toBeVisible();
 await page.getByRole('combobox',{name:'Knowledge version',exact:true}).selectOption({label:'3-empty · draft'});await expect(page.getByRole('heading',{name:'No candidates yet'})).toBeVisible();
 await page.getByText('Upload source · TXT, Markdown or PDF',{exact:true}).click();await page.getByLabel('Source document').setInputFiles({name:'test-only.md',mimeType:'text/markdown',buffer:Buffer.from('Controller test upload from browser.')});await page.getByRole('button',{name:'Upload and extract'}).click();await expect(page.getByRole('button',{name:'Load extracted candidates'})).toBeVisible({timeout:30000});await page.getByRole('button',{name:'Load extracted candidates'}).click();await expect(page.locator('.candidate-row')).toHaveCount(3);
});
test('reader sees released context only, no private drafts, accessible navigation',async({page})=>{
 await login(page,'reader');await expect(page.getByRole('combobox',{name:'Knowledge version',exact:true})).toContainText('2-released');await expect(page.getByRole('combobox',{name:'Knowledge version',exact:true})).not.toContainText('1-draft');
 await page.getByRole('link',{name:'Review Inbox',exact:true}).focus();await page.keyboard.press('Enter');await expect(page.getByRole('heading',{name:'Review requires ownership or contribution access'})).toBeVisible();
 await page.getByRole('link',{name:'Activity',exact:true}).click();await expect(page.getByRole('heading',{name:'publication activated',exact:true})).toBeVisible();await expect(page.getByText('candidate edited',{exact:true})).toHaveCount(0);
 await page.getByRole('link',{name:'Ask Knowledge AI',exact:true}).click();await page.getByLabel('Your question').fill('Controller');await expect(page.getByLabel('Your question')).toHaveValue('Controller');await page.getByRole('button',{name:'Ask selected context'}).click();await expect(page.getByRole('heading',{name:'Answer',exact:true})).toBeVisible();
});
test('publication failure stays separate from approval and can retry',async({page,request})=>{
 await login(page);await review(page);for(const c of await page.locator('.candidate-row > input').all())await c.check();await page.getByRole('button',{name:'Approve selected revisions',exact:true}).click();await expect(page.locator('.candidate-row .tag[data-status=draft]')).toHaveCount(0);
 for(const c of await page.locator('.candidate-row > input').all())await c.check();await request.post(server+'/__test__/fail-publication');await page.getByRole('button',{name:'Publish selected revisions'}).click();await expect(page.getByText('Publication failed',{exact:true})).toBeVisible({timeout:60000});
 await page.getByRole('button',{name:'Retry publication',exact:true}).click();await expect(page.locator('.definition .tag').filter({hasText:'published'})).toBeVisible({timeout:60000});
});
test('administrator creates user, assigned project, version and exact product dependency',async({page})=>{
 await login(page,'admin');await page.getByText('Users',{exact:true}).click();await page.getByLabel('New username',{exact:true}).fill('test-new-reader');await page.getByLabel('Initial password',{exact:true}).fill('test-only-password');await page.getByRole('button',{name:'Create user',exact:true}).click();await expect(page.locator('.rows').getByText('test-new-reader',{exact:false})).toBeVisible();
 await page.getByText('Create profile',{exact:true}).first().click();await page.getByLabel('Name',{exact:true}).fill('UI Test Project');await page.getByRole('combobox',{name:'Kind',exact:true}).selectOption('project');await page.getByRole('combobox',{name:'Assigned owner',exact:true}).selectOption({label:'owner-a'});await page.getByRole('button',{name:'Create profile',exact:true}).click();await expect(page.getByRole('heading',{name:'UI Test Project',exact:true})).toBeVisible();
 await page.getByRole('combobox',{name:'Profile',exact:true}).selectOption({label:'UI Test Project · project'});await page.getByLabel('New version label',{exact:true}).fill('project-1');await page.getByRole('button',{name:'Create version',exact:true}).click();await expect(page.getByRole('heading',{name:'Selected version · project-1'})).toBeVisible();
 await page.getByRole('checkbox',{name:'UI Test Product / 2-released · released'}).check();await page.getByRole('button',{name:'Save dependency pins'}).click();await expect(page.getByRole('status')).toContainText('Exact dependency pins saved');
 await page.getByText('Ownership & access',{exact:true}).click();await page.getByRole('checkbox',{name:'Read access for test-new-reader'}).check();const row=page.getByRole('row').filter({hasText:'test-new-reader'});await row.getByRole('button',{name:'Save grant'}).click();await expect(page.getByRole('status')).toContainText('Profile grant saved');
});
test('owner authors entity attributes, scoring, relation and aliases, qualifies publishes and binds',async({page})=>{
 await login(page);await page.getByRole('combobox',{name:'Knowledge version',exact:true}).selectOption({label:'3-empty · draft'});await page.getByRole('link',{name:'Knowledge Models',exact:true}).click();await page.getByRole('button',{name:'Create model draft'}).click();await expect(page.getByRole('heading',{name:'Model revision 2',exact:true})).toBeVisible();
 await page.getByLabel('Semantic description',{exact:true}).fill('UI test model authored through forms');await page.getByRole('button',{name:'Save description'}).click();
 await page.getByLabel('Entity type name',{exact:true}).fill('Test Machine');await page.getByRole('button',{name:'Add attribute',exact:true}).click();await page.getByLabel('Attribute name',{exact:true}).fill('rating');await page.getByLabel('Description',{exact:true}).fill('Test machine rating');await page.getByLabel('identity',{exact:true}).fill('5');await page.getByLabel('retrieval rationale',{exact:true}).fill('Independent test evidence');await page.getByRole('button',{name:'Save entity definition'}).click();await expect(page.getByRole('heading',{name:'Test Machine',exact:true})).toBeVisible();
 await page.getByLabel('Qualification for Test Machine',{exact:true}).fill('An independent entity with its own lifecycle');await page.getByRole('button',{name:'Qualify Test Machine',exact:true}).click();await expect(page.getByText('Owner qualified',{exact:true})).toBeVisible();
 await page.getByLabel('Relation name',{exact:true}).fill('feeds');await page.getByRole('combobox',{name:'Source entity type',exact:true}).selectOption({label:'Test Machine'});await page.getByRole('combobox',{name:'Target entity type',exact:true}).selectOption({label:'Test Machine'});await page.getByRole('button',{name:'Save relation definition'}).click();await expect(page.getByText('Test Machine → feeds → Test Machine',{exact:true})).toBeVisible();
 await page.getByLabel('Canonical name',{exact:true}).fill('Machine');await page.getByLabel('Aliases · one per line',{exact:true}).fill('Unit\nAsset');await page.getByRole('button',{name:'Save canonical concept'}).click();await expect(page.getByText('Unit, Asset',{exact:true})).toBeVisible();
 await page.getByRole('button',{name:'Publish model',exact:true}).click();await expect(page.getByRole('button',{name:'Bind to selected version'})).toBeVisible();await page.getByRole('button',{name:'Bind to selected version'}).click();await expect(page.getByRole('status')).toContainText('Published model bound');
 await page.setViewportSize({width:1280,height:720});await page.getByRole('button',{name:'Sign out'}).scrollIntoViewIfNeeded();await expect(page.getByRole('button',{name:'Sign out'})).toBeInViewport();await page.evaluate(()=>{window.scrollTo(0,0);document.querySelector('.sidebar')?.scrollTo(0,0);(document.activeElement as HTMLElement)?.blur();});await page.screenshot({path:'/tmp/knowledge-ai-models-acceptance.png'});
});
