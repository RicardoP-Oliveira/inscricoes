const { createApp, ref, reactive, onMounted, nextTick } = Vue
const { createVuetify } = Vuetify
const { createRouter, createWebHashHistory, useRoute, useRouter } = VueRouter

const estado = reactive({ usuario: null, pronto: false })
let aoPerderSessao = function () { }

function lerCookie(nome) {
  const m = document.cookie.match(new RegExp('(?:^|;\\s*)' + nome + '=([^;]+)'))
  return m ? decodeURIComponent(m[1]) : ''
}

async function api(caminho, opcoes) {
  const opt = opcoes || {}
  const metodo = (opt.method || 'GET').toUpperCase()
  const headers = Object.assign({}, opt.headers || {})
  let corpo = opt.body
  if (corpo && typeof corpo !== 'string') {
    corpo = JSON.stringify(corpo)
    headers['Content-Type'] = 'application/json'
  }
  if (metodo !== 'GET' && metodo !== 'HEAD') headers['X-CSRF-Token'] = lerCookie('csrf')
  const resp = await fetch('/api' + caminho, {
    method: metodo, headers: headers, credentials: 'same-origin', body: corpo
  })
  const texto = await resp.text()
  let dados = null
  try { dados = texto ? JSON.parse(texto) : null } catch (e) { dados = null }
  if (resp.status === 401) {
    aoPerderSessao()
    throw new Error((dados && dados.detail) || 'Sessao expirada.')
  }
  if (!resp.ok) throw new Error((dados && dados.detail) || ('Erro ' + resp.status))
  return dados
}

function dataHora(v) { return v ? new Date(v).toLocaleString('pt-BR') : '' }

const PublicoEventos = {
  template: `
  <v-container class="py-8" style="max-width:1000px">
    <div class="d-flex align-center mb-6">
      <h1 class="text-h5">Eventos abertos</h1>
      <v-spacer></v-spacer>
      <v-btn variant="text" to="/login" prepend-icon="mdi-lock-outline">Acesso administrativo</v-btn>
    </div>
    <v-alert v-if="erro" type="error" variant="tonal" class="mb-4">{{ erro }}</v-alert>
    <v-row v-if="eventos.length">
      <v-col v-for="e in eventos" :key="e.id" cols="12" md="6">
        <v-card :to="'/evento/' + e.id" hover>
          <v-card-item>
            <v-card-title class="text-body-1">{{ e.titulo }}</v-card-title>
            <v-card-subtitle>{{ dataHora(e.data_evento) }}</v-card-subtitle>
          </v-card-item>
          <v-card-text>
            <v-progress-linear :model-value="pct(e)" height="8" rounded color="primary"></v-progress-linear>
            <div class="text-caption mt-2">{{ e.ocupantes }} de {{ e.vagas_titulares }} titulares</div>
          </v-card-text>
        </v-card>
      </v-col>
    </v-row>
    <v-alert v-else-if="!carregando" type="info" variant="tonal">Nenhum evento com inscricoes abertas.</v-alert>
    <v-skeleton-loader v-if="carregando" type="card"></v-skeleton-loader>
  </v-container>`,
  setup() {
    const eventos = ref([])
    const carregando = ref(true)
    const erro = ref('')
    function pct(e) { return e.vagas_titulares ? Math.round(100 * e.ocupantes / e.vagas_titulares) : 0 }
    onMounted(async () => {
      try { eventos.value = await api('/eventos/publicos') }
      catch (e) { erro.value = e.message }
      finally { carregando.value = false }
    })
    return { eventos, carregando, erro, pct, dataHora }
  }
}

const EventoDetalhe = {
  template: `
  <v-container class="py-8" style="max-width:820px">
    <v-btn variant="text" prepend-icon="mdi-arrow-left" to="/" class="mb-4">Voltar</v-btn>
    <v-card v-if="evento">
      <v-card-item>
        <v-card-title>{{ evento.titulo }}</v-card-title>
        <v-card-subtitle>{{ dataHora(evento.data_evento) }} - {{ evento.local }}</v-card-subtitle>
      </v-card-item>
      <v-card-text>
        <p class="mb-4" style="white-space:pre-line">{{ evento.descricao }}</p>
        <v-alert v-if="evento.livres > 0" type="success" variant="tonal" density="compact">
          {{ evento.livres }} vaga(s) titular(es) livre(s).
        </v-alert>
        <v-alert v-else type="info" variant="tonal" density="compact">
          Titulares esgotadas: novas inscricoes entram na reserva ({{ evento.vagas_reserva }} posicoes).
        </v-alert>
      </v-card-text>
    </v-card>
    <v-card class="mt-6">
      <v-card-title class="text-subtitle-1">Fazer inscricao</v-card-title>
      <v-card-text>
        <v-form v-on:submit.prevent="enviar">
          <v-text-field v-model="form.nome" label="Nome completo" density="comfortable"></v-text-field>
          <v-text-field v-model="form.documento" label="CPF ou RG" density="comfortable"></v-text-field>
          <v-text-field v-model="form.email" label="E-mail" type="email" density="comfortable"></v-text-field>
          <v-text-field v-model="form.telefone" label="Telefone (opcional)" density="comfortable"></v-text-field>
          <div style="position:absolute;left:-9999px" aria-hidden="true">
            <input v-model="form.website" tabindex="-1" autocomplete="off">
          </div>
          <v-btn type="submit" color="primary" block :loading="enviando">Inscrever-se</v-btn>
        </v-form>
      </v-card-text>
    </v-card>
    <v-snackbar v-model="aviso.visivel" :color="aviso.cor" timeout="8000">{{ aviso.texto }}</v-snackbar>
  </v-container>`,
  setup() {
    const rota = useRoute()
    const evento = ref(null)
    const enviando = ref(false)
    const aviso = reactive({ visivel: false, texto: '', cor: 'success' })
    const form = reactive({ nome: '', documento: '', email: '', telefone: '', website: '' })
    onMounted(async () => {
      try { evento.value = await api('/eventos/publicos/' + rota.params.id) }
      catch (e) { aviso.texto = e.message; aviso.cor = 'error'; aviso.visivel = true }
    })
    async function enviar() {
      enviando.value = true
      try {
        const r = await api('/eventos/publicos/' + rota.params.id + '/inscricoes',
          { method: 'POST', body: form })
        aviso.texto = r.mensagem
        aviso.cor = 'success'
        evento.value = await api('/eventos/publicos/' + rota.params.id)
        console.log('Evento', evento.value)
        form.nome = ''; form.documento = ''; form.email = ''; form.telefone = ''
      } catch (e) {
        aviso.texto = e.message; aviso.cor = 'error'
      } finally {
        aviso.visivel = true; enviando.value = false
      }
    }
    return { evento, enviando, aviso, form, enviar, dataHora }
  }
}

const Confirmar = {
  template: `
  <v-container class="py-10" style="max-width:640px">
    <v-card v-if="erro"><v-card-text>
      <v-alert type="error" variant="tonal">{{ erro }}</v-alert>
      <v-btn class="mt-4" variant="outlined" to="/">Voltar ao inicio</v-btn>
    </v-card-text></v-card>
    <v-card v-else-if="feito">
      <v-card-title class="text-success">Vaga confirmada</v-card-title>
      <v-card-text>
        <v-list density="compact">
          <v-list-item title="Participante" :subtitle="feito.nome"></v-list-item>
          <v-list-item title="Evento" :subtitle="feito.evento"></v-list-item>
          <v-list-item title="Data" :subtitle="dataHora(feito.data_evento)"></v-list-item>
          <v-list-item title="Local" :subtitle="feito.local"></v-list-item>
        </v-list>
        <v-btn class="mt-4" variant="outlined" to="/">Voltar ao inicio</v-btn>
      </v-card-text>
    </v-card>
    <v-card v-else-if="info">
      <v-card-title>Confirmar inscricao</v-card-title>
      <v-card-text>
        <p class="mb-2"><strong>{{ info.nome }}</strong></p>
        <p class="mb-2">{{ info.titulo }}</p>
        <p class="text-caption">Confirme ate {{ dataHora(info.token_expira_em) }}</p>
      </v-card-text>
      <v-card-actions>
        <v-btn color="primary" block :loading="enviando" v-on:click="confirmar">Confirmar minha vaga</v-btn>
      </v-card-actions>
    </v-card>
    <v-skeleton-loader v-else type="card"></v-skeleton-loader>
  </v-container>`,
  setup() {
    const rota = useRoute()
    const info = ref(null)
    const feito = ref(null)
    const erro = ref('')
    const enviando = ref(false)
    onMounted(async () => {
      try { info.value = await api('/confirmar/' + rota.params.token) }
      catch (e) { erro.value = e.message }
    })
    async function confirmar() {
      enviando.value = true
      try { feito.value = await api('/confirmar/' + rota.params.token, { method: 'POST' }) }
      catch (e) { erro.value = e.message }
      finally { enviando.value = false }
    }
    return { info, feito, erro, enviando, confirmar, dataHora }
  }
}

const Login = {
  template: `
  <v-container class="py-10" style="max-width:440px">
    <v-card>
      <v-card-title>Painel administrativo</v-card-title>
      <v-card-text>
        <v-form v-on:submit.prevent="entrar">
          <v-text-field v-model="username" label="Usuario" density="comfortable"></v-text-field>
          <v-text-field v-model="senha" label="Senha" type="password" density="comfortable"></v-text-field>
          <v-btn type="submit" color="primary" block :loading="enviando">Entrar</v-btn>
        </v-form>
        <v-alert v-if="erro" type="error" variant="tonal" density="compact" class="mt-4">{{ erro }}</v-alert>
        <v-btn class="mt-4" variant="text" block to="/">Voltar ao site publico</v-btn>
      </v-card-text>
    </v-card>
  </v-container>`,
  setup() {
    const router = useRouter()
    const username = ref('')
    const senha = ref('')
    const enviando = ref(false)
    const erro = ref('')
    async function entrar() {
      enviando.value = true
      erro.value = ''
      try {
        await api('/auth/login', { method: 'POST', body: { username: username.value, senha: senha.value } })
        estado.usuario = await api('/auth/me')
        router.push('/admin')
      } catch (e) { erro.value = e.message }
      finally { enviando.value = false }
    }
    return { username, senha, enviando, erro, entrar }
  }
}

const AdminEventos = {
  template: `
  <v-container class="py-6" style="max-width:1250px">
    <div class="d-flex align-center mb-4 flex-wrap" style="gap:8px">
      <h1 class="text-h6">Eventos</h1>
      <v-spacer></v-spacer>
      <v-btn variant="text" prepend-icon="mdi-earth" to="/">Site publico</v-btn>
      <v-btn variant="text" prepend-icon="mdi-logout" v-on:click="sair">Sair</v-btn>
      <v-btn color="primary" prepend-icon="mdi-plus" v-on:click="dialogo = true">Novo evento</v-btn>
    </div>
    <v-alert v-if="erro" type="error" variant="tonal" density="compact" class="mb-4">{{ erro }}</v-alert>
    <v-table density="compact">
      <thead><tr>
        <th>Titulo</th><th>Data</th><th>Status</th><th>Titulares</th>
        <th>Reserva</th><th>Confirmados</th><th></th>
      </tr></thead>
      <tbody>
        <tr v-for="e in eventos" :key="e.id">
          <td>{{ e.titulo }}</td>
          <td>{{ dataHora(e.data_evento) }}</td>
          <td><v-chip size="small">{{ e.status }}</v-chip></td>
          <td>{{ e.ocupantes }}/{{ e.vagas_titulares }}</td>
          <td>{{ e.na_fila }}/{{ e.vagas_reserva }}</td>
          <td>{{ e.confirmados }}</td>
          <td class="text-right">
            <v-btn size="x-small" variant="text" :to="'/admin/evento/' + e.id">Abrir</v-btn>
          </td>
        </tr>
        <tr v-if="!eventos.length"><td colspan="7" class="text-medium-emphasis">Nenhum evento.</td></tr>
      </tbody>
    </v-table>
    <v-dialog v-model="dialogo" style="max-width:560px">
      <v-card>
        <v-card-title>Novo evento</v-card-title>
        <v-card-text>
          <v-text-field v-model="novo.titulo" label="Titulo" density="comfortable"></v-text-field>
          <v-textarea v-model="novo.descricao" label="Descricao" rows="2" density="comfortable"></v-textarea>
          <v-text-field v-model="novo.data_evento" label="Data e hora" type="datetime-local" density="comfortable"></v-text-field>
          <v-text-field v-model="novo.local" label="Local" density="comfortable"></v-text-field>
          <v-row dense>
            <v-col cols="4"><v-text-field v-model.number="novo.vagas_titulares" label="Titulares" type="number" density="compact"></v-text-field></v-col>
            <v-col cols="4"><v-text-field v-model.number="novo.vagas_reserva" label="Reservas" type="number" density="compact"></v-text-field></v-col>
            <v-col cols="4"><v-text-field v-model.number="novo.prazo_confirmacao_horas" label="Prazo (h)" type="number" density="compact"></v-text-field></v-col>
          </v-row>
        </v-card-text>
        <v-card-actions>
          <v-spacer></v-spacer>
          <v-btn variant="text" v-on:click="dialogo = false">Cancelar</v-btn>
          <v-btn color="primary" :loading="salvando" v-on:click="criar">Criar</v-btn>
        </v-card-actions>
      </v-card>
    </v-dialog>
  </v-container>`,
  setup() {
    const router = useRouter()
    const eventos = ref([])
    const erro = ref('')
    const dialogo = ref(false)
    const salvando = ref(false)
    const novo = reactive({
      titulo: '', descricao: '', data_evento: '', local: '',
      vagas_titulares: 30, vagas_reserva: 10, prazo_confirmacao_horas: 24
    })
    async function carregar() {
      try { eventos.value = await api('/admin/eventos') }
      catch (e) { erro.value = e.message }
    }
    async function criar() {
      salvando.value = true
      erro.value = ''
      try {
        await api('/admin/eventos', {
          method: 'POST', body: {
            titulo: novo.titulo,
            descricao: novo.descricao,
            data_evento: new Date(novo.data_evento).toISOString(),
            local: novo.local,
            vagas_titulares: Number(novo.vagas_titulares),
            vagas_reserva: Number(novo.vagas_reserva),
            prazo_confirmacao_horas: Number(novo.prazo_confirmacao_horas)
          }
        })
        dialogo.value = false
        await carregar()
      } catch (e) { erro.value = e.message }
      finally { salvando.value = false }
    }
    async function sair() {
      try { await api('/auth/logout', { method: 'POST' }) } catch (e) { }
      estado.usuario = null
      router.push('/login')
    }
    onMounted(carregar)
    return { eventos, erro, dialogo, salvando, novo, criar, sair, dataHora }
  }
}

const AdminPainel = {
  template: `
  <v-container class="py-6" style="max-width:1250px">
    <v-btn variant="text" prepend-icon="mdi-arrow-left" to="/admin" class="mb-2">Eventos</v-btn>
    <div v-if="m">
      <div class="d-flex align-center mb-4 flex-wrap" style="gap:8px">
        <h1 class="text-h6 mr-2">{{ m.ocupacao.titulo }}</h1>
        <v-chip size="small" class="mr-2">{{ m.ocupacao.status }}</v-chip>
        <v-spacer></v-spacer>
        <v-btn size="small" variant="outlined" v-on:click="acao('convocar')">Convocar reservas</v-btn>
        <v-btn size="small" variant="outlined" v-on:click="acao('status/ABERTO')">Abrir</v-btn>
        <v-btn size="small" variant="outlined" v-on:click="acao('status/ENCERRADO')">Encerrar</v-btn>
        <v-btn size="small" variant="outlined" v-on:click="acao('status/FINALIZADO')">Finalizar</v-btn>
      </div>
      <v-row>
        <v-col cols="6" md="2"><v-card><v-card-text>
          <div class="text-caption">Titulares</div>
          <div class="text-h6">{{ m.ocupacao.ocupantes }}/{{ m.ocupacao.vagas_titulares }}</div>
        </v-card-text></v-card></v-col>
        <v-col cols="6" md="2"><v-card><v-card-text>
          <div class="text-caption">Reserva</div>
          <div class="text-h6">{{ m.funil.na_fila }}/{{ m.ocupacao.vagas_reserva }}</div>
        </v-card-text></v-card></v-col>
        <v-col cols="6" md="2"><v-card><v-card-text>
          <div class="text-caption">Confirmados</div>
          <div class="text-h6">{{ m.funil.confirmados }}</div>
        </v-card-text></v-card></v-col>
        <v-col cols="6" md="2"><v-card><v-card-text>
          <div class="text-caption">Convocados</div>
          <div class="text-h6">{{ m.funil.convocados }}</div>
        </v-card-text></v-card></v-col>
        <v-col cols="6" md="2"><v-card><v-card-text>
          <div class="text-caption">Presentes</div>
          <div class="text-h6">{{ m.funil.presentes }}</div>
        </v-card-text></v-card></v-col>
        <v-col cols="6" md="2"><v-card><v-card-text>
          <div class="text-caption">Perdidos</div>
          <div class="text-h6">{{ m.funil.perdidos }}</div>
        </v-card-text></v-card></v-col>
      </v-row>
      <v-card class="mt-4">
        <v-card-title class="text-subtitle-1">Inscricoes por dia</v-card-title>
        <v-card-text><div style="height:260px"><canvas ref="area"></canvas></div></v-card-text>
      </v-card>
      <v-card class="mt-4">
        <v-card-title class="text-subtitle-1">Inscricoes</v-card-title>
        <v-table density="compact">
          <thead><tr>
            <th>Nome</th><th>Documento</th><th>E-mail</th><th>Vaga</th>
            <th>Status</th><th>Ordem</th><th></th>
          </tr></thead>
          <tbody>
            <tr v-for="i in inscricoes" :key="i.id">
              <td>{{ i.nome }}</td>
              <td>{{ i.documento }}</td>
              <td>{{ i.email }}</td>
              <td>{{ i.tipo_vaga }}</td>
              <td>{{ i.status }}</td>
              <td>{{ i.ordem_espera }}</td>
              <td class="text-right" style="white-space:nowrap">
                <v-btn size="x-small" variant="text" :disabled="i.status !== 'CONFIRMADO'" v-on:click="presenca(i)">Check-in</v-btn>
                <v-btn size="x-small" variant="text" color="error" :disabled="i.status === 'CANCELADO' || i.status === 'EXPIRADO'" v-on:click="cancelar(i)">Cancelar</v-btn>
              </td>
            </tr>
            <tr v-if="!inscricoes.length"><td colspan="7" class="text-medium-emphasis">Nenhuma inscricao.</td></tr>
          </tbody>
        </v-table>
      </v-card>
      <v-card class="mt-4">
        <v-card-title class="text-subtitle-1">Links de confirmacao gerados</v-card-title>
        <v-card-text>
          <div v-for="e in emails" :key="e.id" class="mb-4">
            <div class="text-caption text-medium-emphasis">{{ dataHora(e.created_at) }} - {{ e.destinatario }} - {{ e.assunto }}</div>
            <pre class="text-body-2" style="white-space:pre-wrap;margin:0">{{ e.corpo }}</pre>
          </div>
          <div v-if="!emails.length" class="text-caption text-medium-emphasis">Nenhum e-mail gerado.</div>
        </v-card-text>
      </v-card>
    </div>
    <v-skeleton-loader v-else type="article"></v-skeleton-loader>
    <v-snackbar v-model="aviso.visivel" :color="aviso.cor" timeout="6000">{{ aviso.texto }}</v-snackbar>
  </v-container>`,
  setup() {
    const rota = useRoute()
    const id = rota.params.id
    const m = ref(null)
    const inscricoes = ref([])
    const emails = ref([])
    const area = ref(null)
    const aviso = reactive({ visivel: false, texto: '', cor: 'success' })
    let grafico = null
    function desenhar() {
      if (!area.value || !m.value) return
      const serie = m.value.serie || []
      if (grafico) grafico.destroy()
      grafico = new Chart(area.value, {
        type: 'line',
        data: {
          labels: serie.map(function (r) { return r.dia }),
          datasets: [
            {
              label: 'Titulares', data: serie.map(function (r) { return r.total - r.reservas }),
              borderColor: '#1a4d8f', backgroundColor: 'rgba(26,77,143,0.15)', tension: 0.3, fill: true
            },
            {
              label: 'Reservas', data: serie.map(function (r) { return r.reservas }),
              borderColor: '#ef6c00', backgroundColor: 'rgba(239,108,0,0.15)', tension: 0.3, fill: true
            }
          ]
        },
        options: {
          responsive: true, maintainAspectRatio: false,
          plugins: { legend: { position: 'bottom' } },
          scales: { y: { beginAtZero: true, ticks: { precision: 0 } } }
        }
      })
    }
    async function carregar() {
      try {
        const pacote = await Promise.all([
          api('/admin/eventos/' + id + '/metricas'),
          api('/admin/eventos/' + id + '/inscricoes'),
          api('/admin/eventos/' + id + '/emails')
        ])
        m.value = pacote[0]
        inscricoes.value = pacote[1]
        emails.value = pacote[2]
        await nextTick()
        desenhar()
      } catch (e) {
        aviso.texto = e.message; aviso.cor = 'error'; aviso.visivel = true
      }
    }
    async function acao(caminho) {
      try {
        const r = await api('/admin/eventos/' + id + '/' + caminho, { method: 'POST' })
        aviso.texto = (r && r.convocados !== undefined)
          ? (r.convocados + ' convocado(s).') : 'Acao concluida.'
        aviso.cor = 'success'
        await carregar()
      } catch (e) { aviso.texto = e.message; aviso.cor = 'error' }
      aviso.visivel = true
    }
    async function presenca(i) {
      try {
        await api('/admin/eventos/' + id + '/inscricoes/' + i.id + '/presenca', { method: 'POST' })
        aviso.texto = 'Presenca registrada.'; aviso.cor = 'success'
        await carregar()
      } catch (e) { aviso.texto = e.message; aviso.cor = 'error' }
      aviso.visivel = true
    }
    async function cancelar(i) {
      try {
        await api('/admin/eventos/' + id + '/inscricoes/' + i.id + '/cancelar', { method: 'POST' })
        aviso.texto = 'Inscricao cancelada.'; aviso.cor = 'warning'
        await carregar()
      } catch (e) { aviso.texto = e.message; aviso.cor = 'error' }
      aviso.visivel = true
    }
    onMounted(carregar)
    return { m, inscricoes, emails, area, aviso, acao, presenca, cancelar, dataHora }
  }
}

const rotas = [
  { path: '/', component: PublicoEventos },
  { path: '/evento/:id', component: EventoDetalhe },
  { path: '/confirmar/:token', component: Confirmar },
  { path: '/login', component: Login },
  { path: '/admin', component: AdminEventos, meta: { auth: true } },
  { path: '/admin/evento/:id', component: AdminPainel, meta: { auth: true } }
]

const router = createRouter({ history: createWebHashHistory(), routes: rotas })

aoPerderSessao = function () { estado.usuario = null }

router.beforeEach(async function (destino) {
  if (!estado.pronto) {
    try { estado.usuario = await api('/auth/me') }
    catch (e) { estado.usuario = null }
    estado.pronto = true
  }
  if (destino.meta.auth && !estado.usuario) return '/login'
  if (destino.path === '/login' && estado.usuario) return '/admin'
  return true
})

const App = { template: '<v-app><router-view></router-view></v-app>' }

const vuetify = createVuetify({
  theme: { defaultTheme: 'light', themes: { light: { colors: { primary: '#1a4d8f' } } } }
})

createApp(App).use(router).use(vuetify).mount('#app')
