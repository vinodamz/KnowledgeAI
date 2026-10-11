import {defineConfig} from '@playwright/test';
export default defineConfig({testDir:'e2e',workers:1,use:{baseURL:'http://127.0.0.1:9636',headless:true},reporter:'list'});
