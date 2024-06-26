# coding:utf-8

import tensorflow as tf
from keras import backend as K
import numpy as np
import os

NUM_WIDTH = [48, 48]  # [conv, simple]
NUM_STATES = [(nw, nw) for nw in NUM_WIDTH]
NUM_ACTIONS = 2
NONE_STATE = [np.zeros(ns) for ns in NUM_STATES]
class Config:

    def __init__(self, simple, model_name):
        self.frames = 0
        self.isLearned = False       # 学習が終了したことを示すフラグ
        self.sess = tf.Session()
        self.simple = simple
        self.model_name = model_name

from keras.models import Model
from keras.layers import Input, Dense, Flatten
from keras.layers.convolutional import Conv2D
from keras.layers.pooling import MaxPooling2D


def create_model(simple):
    ns = NUM_WIDTH[int(simple)]
    state_input = Input(batch_shape=(None, ns, ns, NUM_STATES), name='state')
    x = state_input
    x = Conv2D(16, (4, 4), padding='same', activation='relu', strides=(2, 2))(state_input)
    x = Conv2D(32, (2, 2), padding='same', activation='relu', strides=(1, 1))(x)
    x = MaxPooling2D(pool_size=(2, 2))(x)
    x = Conv2D(32, (2, 2), padding='same', activation='relu', strides=(1, 1))(x)
    x = Conv2D(64, (2, 2), padding='same', activation='relu', strides=(1, 1))(x)
    x = MaxPooling2D(pool_size=(2, 2))(x)
    x = Flatten()(x)
    x = Dense(256, activation='relu')(x)
    x = Dense(64, activation='relu')(x)
    out_actions = Dense(NUM_ACTIONS, activation='softmax')(x)
    out_value = Dense(1, activation='linear')(x)
    model = Model(inputs=[state_input], outputs=[out_actions, out_value])
    return model



MIN_BATCH = 5
LOSS_V = .5  # v loss coefficient
LOSS_ENTROPY = .01  # entropy coefficient
LEARNING_RATE = 5e-3
RMSPropDecaly = 0.99
#NUM_STATES = 5    # Size of state.
#NONE_STATE = None
#NUM_ACTIONS = 0
MODEL_DIR = "model"

GAMMA = 0.99
N_STEP_RETURN = 5
GAMMA= GAMMA ** N_STEP_RETURN

TRAIN_WORKERS = 10  # Thread number of learning.
TEST_WORKER = 1  # Thread number of testing (default 1)
MAX_STEPS = 20  # Maximum step number.
MAX_TRAIN_NUM = 5000  # Learning number of each thread.
Tmax = 5  # Updating step period of each thread.

# Params of epsilon greedy
EPS_START = 0.5
EPS_END = 0.0

# --各スレッドで走るTensorFlowのDeep Neural Networkのクラスです　-------
class LocalBrain:
    def __init__(self, name, parameter_server, config, thread_type):  # globalなparameter_serverをメンバ変数として持つ
        with tf.name_scope(name):
            self.train_queue = [[], [], [], [], []]  # s, a, r, s', s' terminal mask
            K.set_session(config.sess)
            self.config = config
            self.model = self._build_model()
            self._build_graph(name, parameter_server)  # ネットワークの学習やメソッドを定義

    def _build_model(self):  # Kerasでネットワークの形を定義します
        model = create_model(self.config.simple)
        model._make_predict_function()  # have to initialize before threading
        return model

    def _build_graph(self, name, parameter_server):  # TensorFlowでネットワークの重みをどう学習させるのかを定義します
        ns = NUM_WIDTH[int(self.config.simple)]
        if self.config.simple:
            self.s_t = tf.compat.v1.placeholder(tf.float32, shape=(None, ns, ns))
        else:
            self.s_t = tf.compat.v1.placeholder(tf.float32, shape=(None, ns, ns, NUM_STATES))

        self.a_t = tf.compat.v1.placeholder(tf.float32, shape=(None, NUM_ACTIONS))
        self.r_t = tf.compat.v1.placeholder(tf.float32, shape=(None, 1))  # not immediate, but discounted n step reward

        p, v = self.model(self.s_t)

        # loss関数を定義します
        log_prob = tf.compat.v1.log(tf.reduce_sum(p * self.a_t, axis=1, keep_dims=True) + 1e-10)
        advantage = self.r_t - v
        loss_policy = - log_prob * tf.stop_gradient(advantage)  # stop_gradientでadvantageは定数として扱います
        loss_value = LOSS_V * tf.square(advantage)  # minimize value error
        entropy = LOSS_ENTROPY * tf.reduce_sum(p * tf.compat.v1.log(p + 1e-10), axis=1,
                                               keep_dims=True)  # maximize entropy (regularization)
        self.loss_total = tf.reduce_mean(loss_policy + loss_value + entropy)

        # 重みの変数を定義
        self.weights_params = tf.compat.v1.get_collection(tf.compat.v1.GraphKeys.TRAINABLE_VARIABLES, scope=name)  # パラメータを宣言
        # 勾配を取得する定義
        self.grads = tf.gradients(self.loss_total, self.weights_params)

        # ParameterServerの重み変数を更新する定義(zipで各変数ごとに計算)
        self.update_global_weight_params = \
            parameter_server.optimizer.apply_gradients(zip(self.grads, parameter_server.weights_params))

        # PrameterServerの重み変数の値を、localBrainにコピーする定義
        self.pull_global_weight_params = [l_p.assign(g_p)
                                          for l_p, g_p in zip(self.weights_params, parameter_server.weights_params)]

        # localBrainの重み変数の値を、PrameterServerにコピーする定義
        self.push_local_weight_params = [g_p.assign(l_p)
                                         for g_p, l_p in zip(parameter_server.weights_params, self.weights_params)]

    def pull_parameter_server(self):  # localスレッドがglobalの重みを取得する
        self.config.sess.run(self.pull_global_weight_params)

    def push_parameter_server(self):  # localスレッドの重みをglobalにコピーする
        self.config.sess.run(self.push_local_weight_params)

    def update_parameter_server(self):  # localbrainの勾配でParameterServerの重みを学習・更新します
        if len(self.train_queue[0]) < MIN_BATCH:  # データがたまっていない場合は更新しない
            return

        s, a, r, s_, s_mask = self.train_queue
        self.train_queue = [[], [], [], [], []]
        s = np.array(s)
        a = np.vstack(a)
        r = np.vstack(r)
        s_ = np.array(s_)
        s_mask = np.vstack(s_mask)
        _, v = self.model.predict(s_)

        # N-1ステップあとまでの時間割引総報酬rに、Nから先に得られるであろう総報酬vに割引N乗したものを足します
        r = r + GAMMA * v * s_mask  # set v to 0 where s_ is terminal state
        feed_dict = {self.s_t: s, self.a_t: a, self.r_t: r}  # 重みの更新に使用するデータ
        self.config.sess.run(self.update_global_weight_params, feed_dict)  # ParameterServerの重みを更新

    def predict_p(self, s):  # 状態sから各actionの確率pベクトルを返します
        p, v = self.model.predict(s)
        return p

    def train_push(self, s, a, r, s_):
        self.train_queue[0].append(s)
        self.train_queue[1].append(a)
        self.train_queue[2].append(r)

        if s_ is None:
            self.train_queue[3].append(NONE_STATE[int(self.config.simple)])
            self.train_queue[4].append(0.)
        else:
            self.train_queue[3].append(s_)
            self.train_queue[4].append(1.)

    def load_weight(self):
        self.model.load_weights(os.path.join(MODEL_DIR, 'model_weights.hdf5'))

    def save(self):
        if not os.path.isdir(MODEL_DIR):
            os.makedirs(MODEL_DIR)
        with tf.compat.v1.variable_scope("parameter_server"):
            try:
                json_string = self.model.to_json()
                open(os.path.join(MODEL_DIR, 'model.json'), 'w').write(json_string)
                self.model.save_weights(os.path.join(MODEL_DIR, 'model_weights.hdf5'))
            except:
                pass
