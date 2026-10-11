import {test,expect} from '@playwright/test';
test('owner reviews an exact draft revision',async({page})=>{
 await page.goto('/');
 await page.getByLabel('Username').fill('owner');
 await page.getByLabel('Password').fill('test-only-password');
 await page.getByRole('button',{name:'Sign in',exact:true}).click();
 await page.getByRole('link',{name:'Review Inbox',exact:true}).click();
 await expect(page.getByText('Draft',{exact:true}).first()).toBeVisible();
 await page.getByRole('button',{name:'Approve entity',exact:true}).click();
 await expect(page.getByText('Approved — awaiting publication',{exact:true}).first()).toBeVisible();
});
