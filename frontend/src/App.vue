<script setup lang="ts">
import { ConfigProvider } from 'ant-design-vue'
import { appTheme } from './theme'
</script>

<template>
  <ConfigProvider :theme="appTheme">
    <router-view />
  </ConfigProvider>
</template>
