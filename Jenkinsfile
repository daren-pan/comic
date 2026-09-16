// ============================================================
//  comic 漫画聚合平台 —— Jenkins 流水线（容器化 Jenkins · ssh 部署到宿主）
//
//  写法参考 RuoYi-Cloud/Jenkinsfile-ecs：**构建在 Jenkins 容器里，部署走 ssh 到宿主**。
//  之所以必须走 ssh，是因为 RuoYi 的 Jenkins 是 **dind（Docker-in-Docker）** 形态 ——
//  jenkins 容器里 DOCKER_HOST=tcp://dind:2376，它构建出的镜像落在 **dind 的数据卷**里，
//  宿主的 docker 根本看不见。所以"构建完直接在宿主 compose up"这条捷径不通：
//  镜像必须经 ACR 中转，再由宿主 pull 回来。
//
//  完整链路：
//    1) 前置检查：容器内 docker / python3+pip，以及到宿主的 ssh 通道
//    2) 从 GitHub 拉代码，按 git diff 判断哪些模块变了
//    3) npm 构建前端产物 comic-web/dist
//    4) deploy/build.sh 按序构建 5 个镜像（mysql → web → crawler → api → nginx）
//    5) 推送到阿里云 ACR（命名空间 comic-website）—— 这是唯一的镜像分发通道，不是备份
//    6) ssh 到宿主：pull 新镜像 → 还原成本地名 → compose up -d → 自检
//
//  Jenkins 侧需要：
//    凭据  acr-credentials   ACR 用户名/口令（自动派生 ACR_CREDENTIALS_USR / _PSW）
//          ecs-ssh-key       登录宿主用的私钥（与 RuoYi 共用）
//          —— GitHub 仓库目前公开，拉代码不需要凭据；转私有再补 github-creds
//    工具  NodeJS 名称为 node-18（vite 5 需要 Node 18+）
//    ⚠️ 容器内还要有 python3 + pip（deploy/build.sh 打 wheel 用）—— 见「1/6 前置检查」
//
//  ⚠️ 宿主一次性准备（第一次部署前手工做一次，之后流水线全自动）：
//    1. 建部署目录（默认 /root/comic/deploy）+ 从 deploy/.env.example 复制出 .env，
//       填好 MYSQL_ROOT_PASSWORD 与 COMIC_JWT_SECRET。
//       .env 不入库、流水线**不碰它**；但会把签出的 docker-compose.yml 覆盖到该目录，
//       所以**不要直接在服务器上改 compose**（改了下次发布会被覆盖），要改就改仓库里的。
//    2. .env 里 COMIC_DATA_HOST 必须是**绝对宿主路径**（如 /srv/comic/data）。
//       流水线会拦下相对路径，并顺手建目录 + chown 到 10001（容器内进程的 uid）。
//    3. 宿主执行过一次 docker login 到 ACR（流水线每次也会代做，幂等）。
//
//  参数：DEPLOY_TAG 回滚 / RUN_MIGRATE 老库迁移 / COLLECT 是否带 scheduler 一起部署
// ============================================================
pipeline {
    agent any

    options {
        // 日志时间戳：Jenkins 装了 Timestamper 插件可以打开这行
        // timestamps()
        // 两次发布并发会把「构建 → 推送 → 拉取 → 重启」交错在一起，禁用并发
        disableConcurrentBuilds()
    }

    tools {
        nodejs 'node-18'
    }

    parameters {
        string(name: 'DEPLOY_TAG', defaultValue: '',
               description: '【回滚用】填一个已存在的镜像 tag（形如 b12-a1b2c3d），只做「拉取 + 重启」，跳过构建与推送。留空 = 正常构建发布')
        booleanParam(name: 'RUN_MIGRATE', defaultValue: false,
               description: '启动后对已有数据库跑一遍幂等迁移（tools/add_log_table.py / add_perf_indexes.py / drop_fingerprint_unique.py）。全新空库不需要')
        booleanParam(name: 'COLLECT', defaultValue: false,
               description: '本次是否连同定时采集（comic-scheduler）一起部署。开着 scheduler 就必须勾，否则它不会跟着换新镜像')
    }

    environment {
        // ---------- 镜像仓库：沿用 RuoYi 的 ACR 实例，只换命名空间 ----------
        ACR_REGISTRY    = 'crpi-zu4tna9y8drenzc4.cn-hangzhou.personal.cr.aliyuncs.com'
        ACR_NAMESPACE   = 'comic-website'
        REG             = "${ACR_REGISTRY}/${ACR_NAMESPACE}"
        ACR_CREDENTIALS = credentials('acr-credentials')

        // ---------- 宿主（Jenkins 在容器里，172.17.0.1 即 docker 网桥网关 = 宿主）----------
        ECS_HOST         = '172.17.0.1'
        ECS_USER         = 'root'
        ECS_PORT         = '22'
        // 宿主的**部署目录**（含 .env），按实际路径改
        COMIC_DEPLOY_DIR = '/root/comic/deploy'

        // deploy/build.sh 里写死的本地镜像标签（别改，除非同时改了 build.sh）
        LOCAL_TAG = '1.0.0'
    }

    stages {

        // ============================================================
        // 1/6 前置检查 —— 容器化 Jenkins 特有的坑都在这里拦掉，避免跑到一半才炸
        // ============================================================
        stage('■ 1/6 前置检查') {
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  🔎 检查 Jenkins 容器内的构建环境...'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                sh '''
                    set -e
                    echo "   docker : $(docker --version 2>/dev/null || echo 未安装)"
                    docker info >/dev/null 2>&1 || {
                      echo "!! Jenkins 容器里的 docker 连不上守护进程"
                      echo "   RuoYi 是 dind 形态：需 DOCKER_HOST=tcp://dind:2376 + DOCKER_TLS_VERIFY=1"
                      echo "   + DOCKER_CERT_PATH=/certs/client，且 ruoyi-dind 容器在跑"
                      exit 1
                    }
                    echo "   DOCKER_HOST : ${DOCKER_HOST:-unix:///var/run/docker.sock}"

                    # deploy/build.sh 用 pip wheel 打包，容器里必须有 python3 + pip。
                    # jenkins/jenkins:lts 基于 Debian，自带 Java 但**不含 Python**，这一项最容易缺。
                    if ! python3 -m pip --version >/dev/null 2>&1; then
                      echo "!! Jenkins 容器里没有可用的 python3 + pip —— deploy/build.sh 打 wheel 需要它"
                      echo "   修法一（一次性，容器重建后失效）："
                      echo "     docker exec -u root <jenkins容器名> apt-get update"
                      echo "     docker exec -u root <jenkins容器名> apt-get install -y python3 python3-pip"
                      echo "   修法二（推荐，持久）：自建镜像（FROM jenkins/jenkins:lts-jdk17 + python3-pip）"
                      echo "     推到 ACR 后改 compose 里的 jenkins image，容器重建也不会丢"
                      exit 1
                    fi
                    echo "   python : $(python3 --version)"
                '''

                echo '  🔎 检查到宿主的 ssh 通道...'
                withCredentials([
                    sshUserPrivateKey(
                        credentialsId: 'ecs-ssh-key',
                        keyFileVariable: 'SSH_KEY',
                        passphraseVariable: '',
                        usernameVariable: ''
                    )
                ]) {
                    sh '''
                        ssh -o StrictHostKeyChecking=no -o BatchMode=yes -o ConnectTimeout=8 \
                            -i "$SSH_KEY" -p "$ECS_PORT" "$ECS_USER@$ECS_HOST" \
                            'echo "   宿主 ssh 可达，主机名：$(hostname)" && docker --version && docker compose version --short'
                    '''
                }
                echo '  ✅ 前置检查通过'
            }
        }

        // ============================================================
        // 2/6 拉代码 + 变更检测
        // ============================================================
        stage('■ 2/6 拉代码 & 检测变更') {
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  📥 从 GitHub 拉取代码...'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                // 公开仓库，匿名可读 —— 不传 credentialsId。
                // 若以后转成私有，在下面补一行：credentialsId: 'github-creds'
                git url: 'https://github.com/daren-pan/comic.git',
                    branch: 'main'

                script {
                    def GIT_HASH = sh(script: 'git rev-parse --short HEAD', returnStdout: true).trim()
                    env.UNIQUE_TAG = "b${BUILD_NUMBER}-${GIT_HASH}"
                    // 归一化回滚参数：老任务首次带参数构建时 params 可能为 null
                    env.EFFECTIVE_TAG = (params.DEPLOY_TAG ?: '').toString().trim()
                    echo "🏷️  本次镜像标签: ${env.UNIQUE_TAG}"
                    if (env.EFFECTIVE_TAG != '') {
                        echo "↩️  回滚模式：只部署 ${env.EFFECTIVE_TAG}（跳过 3~5 步）"
                    }

                    // ---- 变更检测只决定「推哪些镜像、动哪些容器」----
                    // 镜像本身一律全量重建：deploy/build.sh 是唯一的构建入口，5 层有固定
                    // 先后顺序，而且构建侧有 Docker 层缓存，重跑很便宜。做增量的目的是两件事 ——
                    // 不把 1GB 的 comic-mysql 每次重推一遍，以及不动没变的服务。
                    echo '🔍 检测哪些模块有变更...'
                    def DIFF = 'ALL'
                    try {
                        def oldCommit = sh(script: 'git rev-parse HEAD~1', returnStdout: true).trim()
                        DIFF = sh(script: "git diff --name-only ${oldCommit} HEAD", returnStdout: true).trim()
                    } catch (Exception e) { }
                    if (DIFF == '') { DIFF = 'ALL' }

                    // 构建脚本 / 编排定义变了 → 一律当全量，避免漏推
                    def INFRA = (DIFF == 'ALL') || DIFF.contains('deploy/build.sh') || DIFF.contains('deploy/docker-compose.yml')

                    env.CHANGED_WEB     = (INFRA || DIFF.contains('comic-web/'))       ? 'true' : 'false'
                    env.CHANGED_CRAWLER = (INFRA || DIFF.contains('crawler-service/')) ? 'true' : 'false'
                    env.CHANGED_API     = (INFRA || DIFF.contains('api-service/'))     ? 'true' : 'false'
                    env.CHANGED_NGINX   = (INFRA || DIFF.contains('deploy/nginx/'))    ? 'true' : 'false'
                    env.CHANGED_MYSQL   = (INFRA || DIFF.contains('deploy/mysql/')
                                                  || DIFF.contains('crawler-service/sql/')) ? 'true' : 'false'

                    // 依赖：comic-api 的 Dockerfile 是 `FROM comic-crawler` + `COPY --from comic-web`，
                    // 所以 crawler / web 任何一边变了，api 都必须跟着重建（前端是烘进 api 镜像的）
                    if (env.CHANGED_WEB == 'true' || env.CHANGED_CRAWLER == 'true') {
                        env.CHANGED_API = 'true'
                    }

                    echo "  Web=${env.CHANGED_WEB}  Crawler=${env.CHANGED_CRAWLER}  Api=${env.CHANGED_API}  Nginx=${env.CHANGED_NGINX}  Mysql=${env.CHANGED_MYSQL}"
                }
            }
        }

        // ============================================================
        // 3/6 npm 前端产物
        // ============================================================
        stage('■ 3/6 npm 前端产物') {
            when { expression { env.EFFECTIVE_TAG == '' } }
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  🎨 构建前端 comic-web/dist...'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                dir('comic-web') {
                    // 用 ci 而不是 install：node_modules 每次重建，避免残留出
                    // "vite: not found"（install 中断留下的残缺目录会一直骗过检查）
                    sh 'npm ci --registry=https://registry.npmmirror.com || npm install --registry=https://registry.npmmirror.com'
                    sh 'npm run build'
                }
                echo '  ✅ 前端构建完成'
            }
        }

        // ============================================================
        // 4/6 构建镜像（顺序固定在 deploy/build.sh）
        // ============================================================
        stage('■ 4/6 构建镜像') {
            when { expression { env.EFFECTIVE_TAG == '' } }
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  🐳 deploy/build.sh（mysql → web → crawler → api → nginx）'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                // ⚠️ 这里的 docker build 打在 Jenkins 容器连着的那个 daemon 上（RuoYi 是 dind），
                //    所以镜像只存在于 dind —— 宿主看不到，必须靠下一步推 ACR 中转。
                // 容器内 pip 源：国内服务器把下面 withEnv 的**两行一起**取消注释会快很多
                // （deploy/build.sh 认这个环境变量）；不打开则容器内走 pypi.org 官方源。
                // withEnv(['PIP_INDEX=https://pypi.tuna.tsinghua.edu.cn/simple']) {
                sh 'bash deploy/build.sh'
                // }
                echo '  ✅ 5 个镜像已就绪（在 Jenkins 侧的 docker 里）'
            }
        }

        // ============================================================
        // 5/6 推送 ACR —— 唯一的镜像分发通道
        // ============================================================
        stage('■ 5/6 推送 ACR') {
            when { expression { env.EFFECTIVE_TAG == '' } }
            steps {
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                echo '  🔐 登录 ACR + 按需推送...'
                echo '━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━'
                // 单引号：让 shell 去展开变量，Groovy 不插值（口令不会进日志）
                sh 'echo "$ACR_CREDENTIALS_PSW" | docker login --username "$ACR_CREDENTIALS_USR" --password-stdin $ACR_REGISTRY'

                script {
                    // 本地名（comic-api:1.0.0）→ 仓库名（<REG>/comic-api:<tag>）
                    def pushImg = { repo ->
                        echo "  📤 ${repo} → ${env.REG}/${repo}:${env.UNIQUE_TAG}"
                        sh "docker tag ${repo}:${env.LOCAL_TAG} ${env.REG}/${repo}:${env.UNIQUE_TAG}"
                        sh "docker push ${env.REG}/${repo}:${env.UNIQUE_TAG}"
                        // latest 只是方便临时拉取；跑服务与回滚永远用不可变 tag
                        sh "docker tag ${repo}:${env.LOCAL_TAG} ${env.REG}/${repo}:latest"
                        sh "docker push ${env.REG}/${repo}:latest"
                    }

                    if (env.CHANGED_WEB     == 'true') pushImg('comic-web')      // api 的 COPY --from 来源，构建期要用
                    if (env.CHANGED_CRAWLER == 'true') pushImg('comic-crawler')
                    if (env.CHANGED_API     == 'true') pushImg('comic-api')
                    if (env.CHANGED_NGINX   == 'true') pushImg('comic-nginx')
                    // comic-mysql 只在 schema / my.cnf 变时才推 —— 它 1.09GB，每次推纯属浪费
                    if (env.CHANGED_MYSQL   == 'true') pushImg('comic-mysql')
                }
            }
        }

        // ============================================================
        // 6/6 部署到宿主（ssh）+ 自检
        // ============================================================
        stage('■ 6/6 部署到宿主 & 自检') {
            steps {
                withCredentials([
                    sshUserPrivateKey(
                        credentialsId: 'ecs-ssh-key',
                        keyFileVariable: 'SSH_KEY',
                        passphraseVariable: '',
                        usernameVariable: ''
                    )
                ]) {
                    script {
                        def DIR     = env.COMIC_DEPLOY_DIR
                        def TAG     = env.EFFECTIVE_TAG != '' ? env.EFFECTIVE_TAG : env.UNIQUE_TAG
                        def PROFILE = params.COLLECT ? '--profile collect ' : ''
                        def TARGET  = "${env.ECS_USER}@${env.ECS_HOST}"
                        // SSH_KEY 由 withCredentials 在运行时注入，用 **单引号 Groovy 字符串**让它保持
                        // 字面 `$SSH_KEY`，交给 shell 在执行时展开 —— 比当成 Groovy 变量插值可靠。
                        def SSHK    = '-o StrictHostKeyChecking=no -o BatchMode=yes -i "$SSH_KEY" -p ' + env.ECS_PORT
                        def SCPK    = '-o StrictHostKeyChecking=no -i "$SSH_KEY" -P ' + env.ECS_PORT

                        // 把脚本经 stdin 交给宿主的 bash 执行（heredoc 定界符带引号 → 本地不做变量展开）。
                        // 这样做的好处：脚本里可以自由使用单/双引号与 $ 变量，不必层层转义。
                        def remote = { String script ->
                            sh "ssh ${SSHK} ${TARGET} 'bash -s' <<'__REMOTE__'\n${script}\n__REMOTE__"
                        }

                        echo "🚀 部署 tag: ${TAG}${PROFILE ? '（含定时采集）' : ''}"
                        echo "   宿主: ${TARGET}:${DIR}"

                        // ---- ① 同步编排定义 + 迁移脚本（宿主不拉代码，这两样由流水线推过去）----
                        remote("mkdir -p ${DIR}/tools")
                        sh "scp ${SCPK} deploy/docker-compose.yml ${TARGET}:${DIR}/docker-compose.yml"
                        if (params.RUN_MIGRATE) {
                            sh "scp ${SCPK} tools/add_log_table.py tools/add_perf_indexes.py tools/drop_fingerprint_unique.py ${TARGET}:${DIR}/tools/"
                        }

                        // ---- ② 环境闸门 ----
                        // COMIC_DATA_HOST 是 bind 挂载用的**宿主路径**：留空或写相对路径会被解析到
                        // 别处，表现是"站点正常但图库空的 / 转存落不了盘"，很难查，所以这里直接拦下。
                        // chown 10001 = 容器内进程的 uid，顺手修掉最常见的一次性踩坑。
                        // 提示信息里用 $PWD 而不是插值路径 —— 上一行已经 cd 过来了。
                        remote('cd ' + DIR + '\n' + '''
                            set -e
                            if [ ! -f .env ]; then
                              echo "!! 宿主部署目录缺少 .env，当前目录：$PWD"
                              echo "   从 deploy/.env.example 复制出 .env，填好 MYSQL_ROOT_PASSWORD 与 COMIC_JWT_SECRET"
                              exit 1
                            fi
                            DH=$(grep -E "^COMIC_DATA_HOST=" .env | tail -1 | cut -d= -f2- || true)
                            case "$DH" in
                              /*) echo "   COMIC_DATA_HOST = $DH" ;;
                              *)  echo "!! COMIC_DATA_HOST 必须是绝对宿主路径（当前：[$DH]）"
                                  echo "   在 .env 里设成例如：COMIC_DATA_HOST=/srv/comic/data"
                                  exit 1 ;;
                            esac
                            mkdir -p "$DH/image_store"
                            chown -R 10001:10001 "$DH" 2>/dev/null || true
                            echo "   数据目录就绪，属主已修正为 10001"
                        ''')

                        // ---- ③ 宿主登录 ACR（口令走 stdin，不落在命令行里；幂等）----
                        sh """
                            echo "\$ACR_CREDENTIALS_PSW" | ssh ${SSHK} ${TARGET} \\
                              'docker login --username ${env.ACR_CREDENTIALS_USR} --password-stdin ${env.ACR_REGISTRY}'
                        """

                        // ---- ④ 确保宿主持有本次要用的镜像，并还原成本地名 ----
                        // 为什么"还原"：docker-compose.yml 里写的是 comic-api:1.0.0。打回本地名后
                        // compose 无需任何改动，本地直跑那套（up.sh / build.sh）继续共用同一份编排文件。
                        // 用「本地有就不拉」而不是无条件 pull：comic-mysql 有 1GB+，层已在本地时纯属浪费。
                        // comic-web 不需要：它只是 api 的构建期来源，内容已烘进 api 镜像。
                        def pullList = ['comic-api', 'comic-nginx', 'comic-mysql']
                        if (params.COLLECT) { pullList.add('comic-crawler') }   // 只有 scheduler 用

                        def pullScript = 'cd ' + DIR + '\nset -e\n'
                        pullList.each { r ->
                            pullScript += "IMG='${env.REG}/${r}:${TAG}'\n"
                            pullScript += 'if docker image inspect "$IMG" >/dev/null 2>&1; then\n'
                            pullScript += '  echo "   本地已有 $IMG"\n'
                            pullScript += 'else\n'
                            pullScript += '  echo "   拉取 $IMG"\n'
                            pullScript += '  docker pull "$IMG"\n'
                            pullScript += 'fi\n'
                            pullScript += "docker tag \"\$IMG\" '${r}:${env.LOCAL_TAG}'\n"
                        }
                        remote(pullScript)

                        // ---- ⑤ 起服务 ----
                        // --no-build：宿主上只有编排文件、没有构建上下文（api/ nginx/ 等目录都不在），
                        // 必须强制"只用现成镜像"，否则 compose 会试图就地构建而失败。
                        // compose 会自己比对镜像 ID，只重建真正换了的容器 —— 没变的服务不会被重启。
                        remote("cd ${DIR} && docker compose ${PROFILE}up -d --no-build && docker compose ${PROFILE}ps")

                        // ---- ⑥ 可选的库迁移（幂等，重复跑不会重复改）----
                        if (params.RUN_MIGRATE) {
                            echo '>>> 迁移已有库（幂等）'
                            ['add_log_table.py', 'add_perf_indexes.py', 'drop_fingerprint_unique.py'].each { t ->
                                remote("cd ${DIR} && docker compose run --rm -T -v ./tools:/app/tools:ro comic-app python tools/${t}")
                            }
                            echo '   ✅ 迁移脚本跑完'
                        }

                        // ---- ⑦ 硬自检：容器内部打自己的接口（不依赖宿主有没有 curl）----
                        remote('cd ' + DIR + '\n' + '''
                            docker compose exec -T comic-app python -c "import urllib.request,json;print('   comic-app /api/health →',json.load(urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=10))['data'])"
                        ''')

                        // ---- ⑧ 软自检：对外入口 HTTP 码 ----
                        // nginx 在 comic-app 真正开始监听前会返回 502，而 up -d 早就返回了，
                        // 所以要重试几轮，而不是刚起来就打一枪。非 200 只告警、不失败构建。
                        remote('cd ' + DIR + '\n' + '''
                            PORT=$(grep -E "^HTTP_PORT=" .env | tail -1 | cut -d= -f2- || true)
                            PORT=${PORT:-80}
                            CODE=""
                            for i in $(seq 1 12); do
                              CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://127.0.0.1:$PORT/" || true)
                              case "$CODE" in 000|502|503|504|"") sleep 3 ;; *) break ;; esac
                            done
                            echo "   对外入口 http://127.0.0.1:$PORT/ → HTTP $CODE"
                            case "$CODE" in
                              200) : ;;
                              *) echo "   返回 $CODE —— 502 多为上游还没就绪，过几秒再试；持续异常看：docker compose logs comic-app" ;;
                            esac
                        ''')

                        echo '  ✅ 部署完成'
                    }
                }
            }
        }
    }

    post {
        success {
            echo ''
            echo '╔══════════════════════════════════════════╗'
            echo "║  ✅ comic Pipeline #${BUILD_NUMBER} 成功！"
            echo "║  镜像 tag: ${env.UNIQUE_TAG}"
            echo '╚══════════════════════════════════════════╝'
            echo "  回滚：用 ${env.UNIQUE_TAG} 之前的一个 tag，触发一次带 DEPLOY_TAG 参数的构建即可"
        }
        failure {
            echo ''
            echo '╔══════════════════════════════════════════╗'
            echo "║  ❌ comic Pipeline #${BUILD_NUMBER} 失败！"
            echo '╚══════════════════════════════════════════╝'
        }
    }
}
