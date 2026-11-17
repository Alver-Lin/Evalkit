import { createRouter, createWebHistory } from 'vue-router'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      component: () => import('@/layouts/AppLayout.vue'),
      children: [
        { path: '', redirect: '/configs' },
        { path: 'configs', name: 'configs', component: () => import('@/views/ConfigsView.vue') },
        {
          path: 'configs/:id',
          name: 'config-detail',
          component: () => import('@/views/ConfigDetailView.vue'),
        },
        { path: 'runs', name: 'runs', component: () => import('@/views/RunsView.vue') },
        {
          path: 'runs/:id',
          name: 'run-detail',
          component: () => import('@/views/ReportView.vue'),
        },
        {
          path: 'graders',
          name: 'graders',
          component: () => import('@/views/GradersView.vue'),
        },
      ],
    },
  ],
})

export default router
