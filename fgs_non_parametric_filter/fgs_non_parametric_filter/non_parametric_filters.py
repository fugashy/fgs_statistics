# -*- coding: utf-8 -*-
import math
from copy import deepcopy

import numpy as np


def create(config, command_model, motion_model, obs_model):
    if config['type'] == 'pf':
        p_num = config['p_num']
        p_num_resample = config['p_resample']
        if p_num < p_num_resample:
            raise ValueError('p num should be less than p num for resampling')
        resample_threshold = config['resample_threshold']
        return ParticleFilter(
            p_num, p_num_resample, resample_threshold, command_model, motion_model, obs_model)
    else:
        raise NotImplementedError('{} is not a type of gaussian filter'.format(
            config['type']))


class ParticleFilter():
    def __init__(
            self, p_num, p_num_resample, resample_threshold,
            command_model, motion_model, obs_model):
        self._p_num = p_num
        self._p_num_resample = p_num_resample
        self._resample_threshold = resample_threshold
        self._motion_model = motion_model
        self._obs_model = obs_model
        self._command_model = command_model

        self._px = np.zeros((self._motion_model.shape[0], p_num))
        self._pw = np.zeros((1, p_num)) + 1.0 / p_num

        # 状態の初期化
        # 分散共分散については過去のものを考慮せずに毎回計算するので保持しない
        self._x_est = np.zeros(self._motion_model.shape)

    def bayesian_update(self, u, z):
        # 設定されたパーティクル数だけ実施する
        for ip in range(self._p_num):
            # 操作モデルをランダムに揺さぶり，そのときの状態を計算する
            # すなわち，パーティクルのばらまきをする
            ud = u + self._command_model.cov @ np.random.randn(u.shape[0], 1)
            p = np.array([self._px[:, ip]]).T
            p = self._motion_model.calc_next_motion(p, ud)

            # パーティクルから観測
            zp = self._obs_model.observe_at(p)

            # そのパーティクルの尤度を更新
            pw = self._pw[0, ip]
            for iz in range(len(zp[:, 0])):
                try:
                    # 事前に観測したときの距離との差
                    # パーティクルから観測すると観測できなかった点も含まれる場合がある
                    # そのためアクセスエラーはスキップする
                    likelihood = self._obs_model.gauss_likelihood(zp[iz], z[iz])
                except IndexError:
                    continue
                pw *= likelihood

            # パーティクルの更新
            self._px[:, ip] = p[:, 0]
            self._pw[0, ip] = pw

        # 正規化
        self._pw /= self._pw.sum()

        # 更新
        # 加重総和
        # 正規化済みなのでスケールは変わらない
        self._x_est = self._px @ self._pw.T
        cov_est = self._calc_cov()

        # リサンプリングする
        # ぶっちゃけわからん
        self._resampling()

        return self._x_est, cov_est

    @property
    def particles(self):
        return self._px, self._pw

    def _calc_cov(self):
        cov = np.zeros(
            (self._motion_model.shape[0], self._motion_model.shape[0]))
        for i in range(self._px.shape[1]):
            dx = (self._px[:, i] - self._x_est)
            cov += self._pw[0, i] * (dx @ dx.T)

        # 原典(python robotics)では速度のばらつきを無視している
        # Why
        cov[:, -1] = 0.0
        cov[-1, :] = 0.0

        return cov

    def _resampling(self):
        # 重みの2乗和
        # 軽く計算したら，尤度分布の尖り具合と相関があるっぽい
        neff = 1.0 / (self._pw @ self._pw.T)[0, 0]

        if neff < self._resample_threshold:
            # 重みの累積配列
            wcum = np.cumsum(self._pw)
            # TODO(fugashy)なんらかのアルゴリズムでリサンプリングすべきIDを得ているが
            # わからない
            base = np.cumsum(
                self._pw * 0.0 + 1 / self._p_num) - 1 / self._p_num
            resample_id = base + np.random.rand(base.shape[0]) / self._p_num

            inds = []
            ind = 0
            for ip in range(self._p_num):
                while resample_id[ip] > wcum[ind]:
                    ind += 1
                inds.append(ind)
            self._px = self._px[:, inds]
            self._pw = np.zeros((1, self._p_num)) + 1.0 / self._p_num
